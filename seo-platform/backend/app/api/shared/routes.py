"""
Shared routes: dashboard stats, health check, gap-to-brief bridge.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, CrawlJob, Brief, GapResult, UsageLog, User
from app.schemas import DashboardStatsResponse, CreateBriefFromGapRequest, BriefResponse
from app.middleware.auth import require_viewer, require_editor
from app.middleware.audit import log_action

router = APIRouter(prefix="/api", tags=["shared"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(func.now()))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    active_projects = await db.execute(
        select(func.count(Project.id)).where(Project.status == "active")
    )
    running_crawls = await db.execute(
        select(func.count(CrawlJob.id)).where(CrawlJob.status.in_(["queued", "crawling", "analyzing"]))
    )
    active_briefs = await db.execute(
        select(func.count(Brief.id)).where(Brief.status.in_(["draft", "researching", "writing", "review"]))
    )
    published = await db.execute(
        select(func.count(Brief.id)).where(Brief.status == "published")
    )
    total_gaps = await db.execute(select(func.count(GapResult.id)))

    from datetime import datetime, timedelta, timezone
    month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    cost = await db.execute(
        select(func.sum(UsageLog.estimated_cost)).where(UsageLog.created_at >= month_ago)
    )

    return DashboardStatsResponse(
        active_projects=active_projects.scalar() or 0,
        running_crawls=running_crawls.scalar() or 0,
        active_briefs=active_briefs.scalar() or 0,
        published_content=published.scalar() or 0,
        total_gap_keywords=total_gaps.scalar() or 0,
        monthly_cost_estimate=float(cost.scalar() or 0),
    )


@router.get("/models")
async def list_models():
    """List available LLM models."""
    return {
        "models": [
            {"id": "claude-sonnet-4", "provider": "anthropic", "name": "Claude Sonnet 4", "tier": "standard"},
            {"id": "claude-opus-4", "provider": "anthropic", "name": "Claude Opus 4", "tier": "premium"},
            {"id": "gpt-4o", "provider": "openai", "name": "GPT-4o", "tier": "standard"},
            {"id": "gemini-2.5-pro", "provider": "google", "name": "Gemini 2.5 Pro", "tier": "standard"},
            {"id": "mistral-large", "provider": "mistral", "name": "Mistral Large", "tier": "standard"},
        ]
    }


# ── Gap-to-Brief Bridge ──

@router.post("/gaps/{gap_id}/create-brief", response_model=BriefResponse)
async def create_brief_from_gap(
    gap_id: UUID,
    body: CreateBriefFromGapRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Bridge: create an Inkwell brief pre-populated from a KeyGap gap result."""
    result = await db.execute(select(GapResult).where(GapResult.id == gap_id))
    gap = result.scalar_one_or_none()
    if not gap:
        raise HTTPException(status_code=404, detail="Gap result not found")

    # Pre-populate brief from gap data
    title = body.title or f"Content for: {gap.keyword}"

    brief = Brief(
        title=title,
        primary_keyword=gap.keyword,
        lsi_keywords=[],  # TODO: Pull related gap keywords as LSI
        target_word_count=body.target_word_count,
        llm_model=body.llm_model,
        style_guide=body.style_guide,
        gap_result_id=gap.id,
        created_by=user.id,
    )
    db.add(brief)
    await db.flush()

    # Link gap result back to brief
    gap.brief_id = brief.id

    await log_action(db, user.id, "gap.create_brief", "brief", brief.id,
                     details={"gap_keyword": gap.keyword, "gap_id": str(gap.id)})
    return brief
