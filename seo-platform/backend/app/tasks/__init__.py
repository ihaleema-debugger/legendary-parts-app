"""
Celery task stubs — each will be implemented in its own module during development.
These are registered here for the task discovery system.
"""

from app.tasks.worker import celery_app


# ═══════════════════════════════════════════════
# KEYGAP TASKS
# ═══════════════════════════════════════════════

@celery_app.task(name="app.tasks.crawl.crawl_site", bind=True, max_retries=3)
def crawl_site(self, crawl_job_id: str):
    """Crawl a competitor site and extract page data."""
    # TODO: Implement Scrapy/Playwright crawl pipeline
    # 1. Fetch sitemap
    # 2. Breadth-first crawl
    # 3. Extract structured data per page
    # 4. Pass to NLP pipeline
    # 5. Update crawl_job progress via WebSocket
    pass


@celery_app.task(name="app.tasks.crawl.reindex_main_site")
def reindex_main_site():
    """Weekly incremental re-index of legendary-parts.com."""
    # TODO: Check sitemap lastmod, re-crawl changed pages
    pass


@celery_app.task(name="app.tasks.crawl.run_gap_analysis", bind=True)
def run_gap_analysis(self, project_id: str):
    """Compare competitor keywords against main site index."""
    # TODO: Implement gap detection + opportunity scoring
    pass


@celery_app.task(name="app.tasks.crawl.enrich_semrush", bind=True, rate_limit="10/m")
def enrich_semrush(self, keyword_batch: list):
    """Fetch Semrush metrics for a batch of keywords."""
    # TODO: Batch API call, cache results
    pass


# ═══════════════════════════════════════════════
# INKWELL TASKS
# ═══════════════════════════════════════════════

@celery_app.task(name="app.tasks.research.run_research", bind=True)
def run_research(self, brief_id: str):
    """Research phase: SerpAPI search + Playwright extraction."""
    # TODO: Generate queries, fetch results, extract content, summarise
    pass


@celery_app.task(name="app.tasks.writer.generate_outline", bind=True)
def generate_outline(self, brief_id: str):
    """Generate H2/H3 outline from brief + research."""
    # TODO: LLM call via LiteLLM
    pass


@celery_app.task(name="app.tasks.writer.write_content", bind=True)
def write_content(self, brief_id: str):
    """Section-by-section content generation with streaming."""
    # TODO: Loop through outline sections, LLM call per section, stream via WebSocket
    pass


@celery_app.task(name="app.tasks.writer.revise_section", bind=True)
def revise_section(self, section_id: str, instruction: str):
    """Revise a single section based on user instruction."""
    # TODO: LLM call with section context + instruction
    pass


@celery_app.task(name="app.tasks.validation.validate_content", bind=True)
def validate_content(self, brief_id: str):
    """Run SEO validation rule engine."""
    # TODO: Check keyword placement, density, headings, meta, readability
    pass


@celery_app.task(name="app.tasks.plagiarism.check_plagiarism", bind=True)
def check_plagiarism(self, brief_id: str):
    """Run Copyscape + internal MinHash deduplication."""
    # TODO: Copyscape API + internal fingerprint comparison
    pass


# ═══════════════════════════════════════════════
# MAINTENANCE TASKS
# ═══════════════════════════════════════════════

@celery_app.task(name="app.tasks.maintenance.backup_database")
def backup_database():
    """Daily automated PostgreSQL backup."""
    # TODO: pg_dump to backup storage
    pass


@celery_app.task(name="app.tasks.maintenance.cleanup_expired_cache")
def cleanup_expired_cache():
    """Clean up expired Semrush cache entries and old research data."""
    # TODO: Delete semrush_metrics older than cache TTL
    pass
