"""
KeyGap API routers: projects, crawls, keywords, gaps.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, CrawlJob, Keyword, GapResult, Page, User
from app.schemas import (
    ProjectCreate, ProjectUpdate, ProjectResponse,
    CrawlCreate, CrawlResponse,
    KeywordResponse, GapResultResponse, IndexStatusResponse,
)
from app.middleware.auth import require_editor, require_viewer, get_current_user
from app.middleware.audit import log_action

router = APIRouter(prefix="/api", tags=["keygap"])


# ── Projects ──

@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    project = Project(
        name=body.name,
        main_domain=body.main_domain,
        competitor_domains=body.competitor_domains,
        created_by=user.id,
    )
    db.add(project)
    await db.flush()
    await log_action(db, user.id, "project.create", "project", project.id)
    return project


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    q = select(Project)
    if status:
        q = q.where(Project.status == status)
    q = q.order_by(Project.created_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    await log_action(db, user.id, "project.update", "project", project.id)
    return project


@router.delete("/projects/{project_id}")
async def archive_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.status = "archived"
    await log_action(db, user.id, "project.archive", "project", project.id)
    return {"message": "Project archived"}


# ── Crawls ──

@router.post("/crawls", response_model=CrawlResponse)
async def start_crawl(
    body: CrawlCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    job = CrawlJob(
        project_id=body.project_id,
        target_domain=body.target_domain,
        job_type=body.job_type,
        config=body.config,
        triggered_by=user.id,
    )
    db.add(job)
    await db.flush()

    # TODO: Dispatch Celery task for crawling
    # from app.tasks.crawl import crawl_site
    # crawl_site.delay(str(job.id))

    await log_action(db, user.id, "crawl.start", "crawl_job", job.id,
                     details={"domain": body.target_domain})
    return job


@router.get("/crawls", response_model=List[CrawlResponse])
async def list_crawls(
    project_id: Optional[UUID] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    q = select(CrawlJob)
    if project_id:
        q = q.where(CrawlJob.project_id == project_id)
    if status:
        q = q.where(CrawlJob.status == status)
    q = q.order_by(CrawlJob.created_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/crawls/{crawl_id}", response_model=CrawlResponse)
async def get_crawl(
    crawl_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    result = await db.execute(select(CrawlJob).where(CrawlJob.id == crawl_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return job


@router.post("/crawls/{crawl_id}/stop")
async def stop_crawl(
    crawl_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(CrawlJob).where(CrawlJob.id == crawl_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    # TODO: Revoke Celery task
    job.status = "failed"
    await log_action(db, user.id, "crawl.stop", "crawl_job", job.id)
    return {"message": "Crawl stopped"}


# ── Index ──

@router.post("/index/refresh")
async def refresh_index(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    # TODO: Dispatch re-index Celery task
    await log_action(db, user.id, "index.refresh")
    return {"message": "Index refresh queued"}


@router.get("/index/status", response_model=IndexStatusResponse)
async def get_index_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    kw_count = await db.execute(
        select(func.count(Keyword.id)).where(Keyword.source == "main_site")
    )
    page_count = await db.execute(select(func.count(Page.id)))

    return IndexStatusResponse(
        total_keywords=kw_count.scalar() or 0,
        total_pages=page_count.scalar() or 0,
        last_indexed_at=None,  # TODO: Track from last main_index crawl job
        status="ready",
    )


# ── Keywords ──

@router.get("/keywords", response_model=List[KeywordResponse])
async def list_keywords(
    category: Optional[str] = None,
    source: Optional[str] = None,
    domain: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    q = select(Keyword)
    if category:
        q = q.where(Keyword.category == category)
    if source:
        q = q.where(Keyword.source == source)
    if domain:
        q = q.where(Keyword.domain == domain)
    if search:
        q = q.where(Keyword.keyword.ilike(f"%{search}%"))
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


# ── Gaps ──

@router.get("/gaps/{project_id}", response_model=List[GapResultResponse])
async def get_gaps(
    project_id: UUID,
    min_score: Optional[float] = None,
    category: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    q = select(GapResult).where(GapResult.project_id == project_id)
    if min_score:
        q = q.where(GapResult.opportunity_score >= min_score)
    if category:
        q = q.where(GapResult.category == category)
    q = q.order_by(GapResult.opportunity_score.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/gaps/{project_id}/run")
async def run_gap_analysis(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    # TODO: Dispatch Celery task for gap analysis
    await log_action(db, user.id, "gap_analysis.run", "project", project_id)
    return {"message": "Gap analysis queued"}


@router.get("/gaps/{project_id}/export")
async def export_gaps(
    project_id: UUID,
    format: str = Query(default="csv", regex="^(csv|pdf)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    # TODO: Generate CSV/PDF export
    return {"message": f"Export in {format} format queued"}
