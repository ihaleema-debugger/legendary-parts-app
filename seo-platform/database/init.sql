-- ═══════════════════════════════════════════════════════════
-- SEO Platform — Database Initialisation
-- This runs once on first docker-compose up via
-- /docker-entrypoint-initdb.d/
-- After initial setup, all changes go through Alembic migrations.
-- ═══════════════════════════════════════════════════════════

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ──────────────────────────────────────────────────────────
-- ENUM TYPES
-- ──────────────────────────────────────────────────────────
CREATE TYPE user_role AS ENUM ('admin', 'editor', 'viewer');
CREATE TYPE project_status AS ENUM ('active', 'archived');
CREATE TYPE crawl_job_type AS ENUM ('competitor_crawl', 'main_index', 're_index');
CREATE TYPE crawl_status AS ENUM ('queued', 'crawling', 'analyzing', 'complete', 'failed');
CREATE TYPE page_type AS ENUM ('product', 'category', 'blog', 'landing', 'other');
CREATE TYPE keyword_category AS ENUM ('primary', 'service', 'problem', 'local');
CREATE TYPE keyword_source AS ENUM ('competitor', 'main_site');
CREATE TYPE brief_status AS ENUM ('draft', 'researching', 'writing', 'review', 'published');
CREATE TYPE research_depth AS ENUM ('light', 'standard', 'deep');
CREATE TYPE reference_style AS ENUM ('inline', 'footnotes', 'endnotes');

-- ──────────────────────────────────────────────────────────
-- SHARED TABLES
-- ──────────────────────────────────────────────────────────

-- Users
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name       VARCHAR(255) NOT NULL,
    role            user_role NOT NULL DEFAULT 'viewer',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);
CREATE INDEX idx_users_email ON users (email);
CREATE INDEX idx_users_role ON users (role);

-- Audit log
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     UUID,
    details         JSONB DEFAULT '{}',
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_log_action ON audit_log (action);
CREATE INDEX idx_audit_log_user ON audit_log (user_id);
CREATE INDEX idx_audit_log_created ON audit_log (created_at DESC);
CREATE INDEX idx_audit_log_resource ON audit_log (resource_type, resource_id);

-- API key vault
CREATE TABLE api_keys_vault (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service         VARCHAR(50) UNIQUE NOT NULL,
    encrypted_key   TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_rotated_at TIMESTAMPTZ,
    updated_by      UUID REFERENCES users(id) ON DELETE SET NULL
);

-- System settings
CREATE TABLE system_settings (
    key             VARCHAR(100) PRIMARY KEY,
    value           JSONB NOT NULL,
    category        VARCHAR(50),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by      UUID REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_settings_category ON system_settings (category);

-- Refresh tokens
CREATE TABLE refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT UNIQUE NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked         BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_refresh_tokens_user ON refresh_tokens (user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens (token_hash);

-- ──────────────────────────────────────────────────────────
-- KEYGAP TABLES
-- ──────────────────────────────────────────────────────────

-- Projects
CREATE TABLE projects (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(255) NOT NULL,
    main_domain         VARCHAR(255) NOT NULL,
    competitor_domains  JSONB NOT NULL DEFAULT '[]',
    created_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    status              project_status NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_projects_status ON projects (status);

-- Crawl jobs
CREATE TABLE crawl_jobs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target_domain   VARCHAR(255) NOT NULL,
    job_type        crawl_job_type NOT NULL,
    status          crawl_status NOT NULL DEFAULT 'queued',
    pages_crawled   INTEGER NOT NULL DEFAULT 0,
    pages_total     INTEGER,
    config          JSONB DEFAULT '{}',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    triggered_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_crawl_jobs_project ON crawl_jobs (project_id);
CREATE INDEX idx_crawl_jobs_status ON crawl_jobs (status);

-- Pages
CREATE TABLE pages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    crawl_job_id    UUID NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    title           TEXT,
    meta_description TEXT,
    h1_tags         JSONB DEFAULT '[]',
    h2_tags         JSONB DEFAULT '[]',
    body_text       TEXT,
    page_type       page_type,
    crawled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pages_crawl_job ON pages (crawl_job_id);
CREATE INDEX idx_pages_url ON pages USING hash (url);

-- Keywords
CREATE TABLE keywords (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    keyword             TEXT NOT NULL,
    category            keyword_category NOT NULL,
    source              keyword_source NOT NULL,
    page_id             UUID REFERENCES pages(id) ON DELETE CASCADE,
    project_id          UUID REFERENCES projects(id) ON DELETE CASCADE,
    domain              VARCHAR(255),
    extraction_method   VARCHAR(50),
    confidence          FLOAT
);
CREATE INDEX idx_keywords_keyword ON keywords (keyword);
CREATE INDEX idx_keywords_project ON keywords (project_id);
CREATE INDEX idx_keywords_domain ON keywords (domain);
CREATE INDEX idx_keywords_category ON keywords (category);
CREATE INDEX idx_keywords_source ON keywords (source);

-- Semrush metrics cache
CREATE TABLE semrush_metrics (
    keyword             TEXT PRIMARY KEY,
    search_volume       INTEGER,
    keyword_difficulty  FLOAT,
    cpc                 DECIMAL(8,2),
    competitive_density FLOAT,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Gap results
CREATE TABLE gap_results (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id              UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    keyword                 TEXT NOT NULL,
    category                keyword_category,
    competitor_domains      JSONB DEFAULT '[]',
    opportunity_score       FLOAT,
    suggested_content_type  VARCHAR(50),
    suggestion_detail       TEXT,
    brief_id                UUID,  -- FK added after briefs table created
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_gap_results_project ON gap_results (project_id);
CREATE INDEX idx_gap_results_score ON gap_results (opportunity_score DESC);

-- ──────────────────────────────────────────────────────────
-- INKWELL TABLES
-- ──────────────────────────────────────────────────────────

-- Content briefs
CREATE TABLE briefs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title               TEXT NOT NULL,
    primary_keyword     TEXT NOT NULL,
    lsi_keywords        JSONB NOT NULL DEFAULT '[]',
    keyword_instructions TEXT,
    seo_instructions    TEXT,
    target_word_count   INTEGER NOT NULL DEFAULT 2500,
    style_guide         TEXT,
    llm_model           VARCHAR(50) NOT NULL DEFAULT 'claude-sonnet-4',
    research_depth      research_depth NOT NULL DEFAULT 'standard',
    reference_style     reference_style NOT NULL DEFAULT 'inline',
    status              brief_status NOT NULL DEFAULT 'draft',
    gap_result_id       UUID REFERENCES gap_results(id) ON DELETE SET NULL,
    created_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_briefs_status ON briefs (status);
CREATE INDEX idx_briefs_keyword ON briefs (primary_keyword);

-- Add FK from gap_results → briefs now that briefs exists
ALTER TABLE gap_results
    ADD CONSTRAINT fk_gap_results_brief
    FOREIGN KEY (brief_id) REFERENCES briefs(id) ON DELETE SET NULL;

-- Research notes
CREATE TABLE research_notes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brief_id        UUID NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    source_url      TEXT NOT NULL,
    source_title    TEXT,
    source_domain   VARCHAR(255),
    extracted_text  TEXT,
    summary         TEXT,
    is_authority    BOOLEAN NOT NULL DEFAULT FALSE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_research_notes_brief ON research_notes (brief_id);

-- Content sections
CREATE TABLE content_sections (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brief_id        UUID NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    heading         TEXT NOT NULL,
    heading_level   INTEGER NOT NULL CHECK (heading_level IN (2, 3)),
    content         TEXT,
    sort_order      INTEGER NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    keyword_targets JSONB DEFAULT '[]'
);
CREATE INDEX idx_content_sections_brief ON content_sections (brief_id);

-- Section versions
CREATE TABLE section_versions (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    section_id              UUID NOT NULL REFERENCES content_sections(id) ON DELETE CASCADE,
    version                 INTEGER NOT NULL,
    content                 TEXT NOT NULL,
    revision_instruction    TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_section_versions_section ON section_versions (section_id);

-- Validation results
CREATE TABLE validation_results (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brief_id            UUID NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    checks              JSONB NOT NULL DEFAULT '[]',
    overall_score       FLOAT,
    plagiarism_result   JSONB,
    validated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_validation_results_brief ON validation_results (brief_id);

-- ──────────────────────────────────────────────────────────
-- USAGE TRACKING
-- ──────────────────────────────────────────────────────────

CREATE TABLE usage_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    service         VARCHAR(50) NOT NULL,  -- semrush, anthropic, openai, google, mistral, serpapi, copyscape
    module          VARCHAR(20) NOT NULL,  -- keygap, inkwell
    operation       VARCHAR(100),
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    api_calls       INTEGER DEFAULT 1,
    estimated_cost  DECIMAL(10,4) DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_usage_log_service ON usage_log (service);
CREATE INDEX idx_usage_log_user ON usage_log (user_id);
CREATE INDEX idx_usage_log_created ON usage_log (created_at DESC);
CREATE INDEX idx_usage_log_module ON usage_log (module);

-- ──────────────────────────────────────────────────────────
-- DEFAULT SYSTEM SETTINGS
-- ──────────────────────────────────────────────────────────

INSERT INTO system_settings (key, value, category) VALUES
    ('crawl.default_rate_limit', '2', 'keygap'),
    ('crawl.default_depth', '0', 'keygap'),
    ('crawl.respect_robots_txt', 'true', 'keygap'),
    ('semrush.cache_ttl_days', '7', 'keygap'),
    ('gap.min_volume', '50', 'keygap'),
    ('gap.max_difficulty', '80', 'keygap'),
    ('inkwell.default_model', '"claude-sonnet-4"', 'inkwell'),
    ('inkwell.default_research_depth', '"standard"', 'inkwell'),
    ('inkwell.min_compliance_score', '90', 'inkwell'),
    ('inkwell.copyscape_threshold', '10', 'inkwell'),
    ('system.backup_schedule', '"0 3 * * *"', 'system'),
    ('billing.budget_alert_threshold', '100', 'billing')
ON CONFLICT (key) DO NOTHING;
