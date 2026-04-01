"""
SQLAlchemy ORM models for the entire platform.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, Enum, ForeignKey,
    DateTime, JSON, Numeric, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# ═══════════════════════════════════════════════
# SHARED MODELS
# ═══════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(Text, nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(
        Enum("admin", "editor", "viewer", name="user_role", create_type=False),
        nullable=False, default="viewer"
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    audit_entries = relationship("AuditLog", back_populates="user")
    projects = relationship("Project", back_populates="creator")
    briefs = relationship("Brief", back_populates="creator")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50))
    resource_id = Column(UUID(as_uuid=True))
    details = Column(JSONB, default={})
    ip_address = Column(INET)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_entries")


class ApiKeyVault(Base):
    __tablename__ = "api_keys_vault"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service = Column(String(50), unique=True, nullable=False)
    encrypted_key = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_rotated_at = Column(DateTime(timezone=True))
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSONB, nullable=False)
    category = Column(String(50), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(Text, unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked = Column(Boolean, nullable=False, default=False)


# ═══════════════════════════════════════════════
# KEYGAP MODELS
# ═══════════════════════════════════════════════

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    main_domain = Column(String(255), nullable=False)
    competitor_domains = Column(JSONB, nullable=False, default=[])
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(
        Enum("active", "archived", name="project_status", create_type=False),
        nullable=False, default="active"
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    creator = relationship("User", back_populates="projects")
    crawl_jobs = relationship("CrawlJob", back_populates="project", cascade="all, delete-orphan")
    gap_results = relationship("GapResult", back_populates="project", cascade="all, delete-orphan")


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    target_domain = Column(String(255), nullable=False)
    job_type = Column(
        Enum("competitor_crawl", "main_index", "re_index", name="crawl_job_type", create_type=False),
        nullable=False
    )
    status = Column(
        Enum("queued", "crawling", "analyzing", "complete", "failed", name="crawl_status", create_type=False),
        nullable=False, default="queued"
    )
    pages_crawled = Column(Integer, nullable=False, default=0)
    pages_total = Column(Integer)
    config = Column(JSONB, default={})
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="crawl_jobs")
    pages = relationship("Page", back_populates="crawl_job", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text, nullable=False)
    title = Column(Text)
    meta_description = Column(Text)
    h1_tags = Column(JSONB, default=[])
    h2_tags = Column(JSONB, default=[])
    body_text = Column(Text)
    page_type = Column(
        Enum("product", "category", "blog", "landing", "other", name="page_type", create_type=False)
    )
    crawled_at = Column(DateTime(timezone=True), server_default=func.now())

    crawl_job = relationship("CrawlJob", back_populates="pages")
    keywords = relationship("Keyword", back_populates="page", cascade="all, delete-orphan")


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keyword = Column(Text, nullable=False, index=True)
    category = Column(
        Enum("primary", "service", "problem", "local", name="keyword_category", create_type=False),
        nullable=False
    )
    source = Column(
        Enum("competitor", "main_site", name="keyword_source", create_type=False),
        nullable=False
    )
    page_id = Column(UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    domain = Column(String(255), index=True)
    extraction_method = Column(String(50))
    confidence = Column(Float)

    page = relationship("Page", back_populates="keywords")


class SemrushMetric(Base):
    __tablename__ = "semrush_metrics"

    keyword = Column(Text, primary_key=True)
    search_volume = Column(Integer)
    keyword_difficulty = Column(Float)
    cpc = Column(Numeric(8, 2))
    competitive_density = Column(Float)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())


class GapResult(Base):
    __tablename__ = "gap_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    keyword = Column(Text, nullable=False)
    category = Column(
        Enum("primary", "service", "problem", "local", name="keyword_category", create_type=False)
    )
    competitor_domains = Column(JSONB, default=[])
    opportunity_score = Column(Float, index=True)
    suggested_content_type = Column(String(50))
    suggestion_detail = Column(Text)
    brief_id = Column(UUID(as_uuid=True), ForeignKey("briefs.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="gap_results")
    brief = relationship("Brief", back_populates="gap_result")


# ═══════════════════════════════════════════════
# INKWELL MODELS
# ═══════════════════════════════════════════════

class Brief(Base):
    __tablename__ = "briefs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    primary_keyword = Column(Text, nullable=False)
    lsi_keywords = Column(JSONB, nullable=False, default=[])
    keyword_instructions = Column(Text)
    seo_instructions = Column(Text)
    target_word_count = Column(Integer, nullable=False, default=2500)
    style_guide = Column(Text)
    llm_model = Column(String(50), nullable=False, default="claude-sonnet-4")
    research_depth = Column(
        Enum("light", "standard", "deep", name="research_depth", create_type=False),
        nullable=False, default="standard"
    )
    reference_style = Column(
        Enum("inline", "footnotes", "endnotes", name="reference_style", create_type=False),
        nullable=False, default="inline"
    )
    status = Column(
        Enum("draft", "researching", "writing", "review", "published", name="brief_status", create_type=False),
        nullable=False, default="draft"
    )
    gap_result_id = Column(UUID(as_uuid=True), ForeignKey("gap_results.id", ondelete="SET NULL"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    creator = relationship("User", back_populates="briefs")
    gap_result = relationship("GapResult", back_populates="brief")
    research_notes = relationship("ResearchNote", back_populates="brief", cascade="all, delete-orphan")
    sections = relationship("ContentSection", back_populates="brief", cascade="all, delete-orphan")
    validations = relationship("ValidationResult", back_populates="brief", cascade="all, delete-orphan")


class ResearchNote(Base):
    __tablename__ = "research_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id = Column(UUID(as_uuid=True), ForeignKey("briefs.id", ondelete="CASCADE"), nullable=False)
    source_url = Column(Text, nullable=False)
    source_title = Column(Text)
    source_domain = Column(String(255))
    extracted_text = Column(Text)
    summary = Column(Text)
    is_authority = Column(Boolean, nullable=False, default=False)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    brief = relationship("Brief", back_populates="research_notes")


class ContentSection(Base):
    __tablename__ = "content_sections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id = Column(UUID(as_uuid=True), ForeignKey("briefs.id", ondelete="CASCADE"), nullable=False)
    heading = Column(Text, nullable=False)
    heading_level = Column(Integer, nullable=False)
    content = Column(Text)
    sort_order = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    keyword_targets = Column(JSONB, default=[])

    brief = relationship("Brief", back_populates="sections")
    versions = relationship("SectionVersion", back_populates="section", cascade="all, delete-orphan")


class SectionVersion(Base):
    __tablename__ = "section_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(UUID(as_uuid=True), ForeignKey("content_sections.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    revision_instruction = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    section = relationship("ContentSection", back_populates="versions")


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id = Column(UUID(as_uuid=True), ForeignKey("briefs.id", ondelete="CASCADE"), nullable=False)
    checks = Column(JSONB, nullable=False, default=[])
    overall_score = Column(Float)
    plagiarism_result = Column(JSONB)
    validated_at = Column(DateTime(timezone=True), server_default=func.now())

    brief = relationship("Brief", back_populates="validations")


# ═══════════════════════════════════════════════
# USAGE TRACKING
# ═══════════════════════════════════════════════

class UsageLog(Base):
    __tablename__ = "usage_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    service = Column(String(50), nullable=False)
    module = Column(String(20), nullable=False)
    operation = Column(String(100))
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    api_calls = Column(Integer, default=1)
    estimated_cost = Column(Numeric(10, 4), default=0)
    metadata = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
