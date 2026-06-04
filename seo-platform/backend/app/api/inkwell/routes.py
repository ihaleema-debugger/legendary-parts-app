"""
Inkwell API routers: briefs, pipeline, sections, export.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Brief, ContentSection, SectionVersion, ResearchNote, ValidationResult, User
from app.schemas import (
    BriefCreate, BriefUpdate, BriefResponse,
    SectionResponse, RevisionRequest,
    ResearchNoteResponse, ValidationResponse,
)
from app.middleware.auth import require_editor, require_viewer
from app.middleware.audit import log_action

router = APIRouter(prefix="/api", tags=["inkwell"])


# ── Briefs ──

@router.post("/briefs", response_model=BriefResponse)
async def create_brief(
    body: BriefCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    brief = Brief(
        title=body.title,
        primary_keyword=body.primary_keyword,
        lsi_keywords=[kw.model_dump() for kw in body.lsi_keywords],
        keyword_instructions=body.keyword_instructions,
        seo_instructions=body.seo_instructions,
        target_word_count=body.target_word_count,
        style_guide=body.style_guide,
        llm_model=body.llm_model,
        research_depth=body.research_depth,
        reference_style=body.reference_style,
        gap_result_id=body.gap_result_id,
        created_by=user.id,
    )
    db.add(brief)
    await db.flush()
    await log_action(db, user.id, "brief.create", "brief", brief.id)
    return brief


@router.get("/briefs", response_model=List[BriefResponse])
async def list_briefs(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    q = select(Brief)
    if status:
        q = q.where(Brief.status == status)
    q = q.order_by(Brief.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/briefs/{brief_id}", response_model=BriefResponse)
async def get_brief(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    return brief


@router.put("/briefs/{brief_id}", response_model=BriefResponse)
async def update_brief(
    brief_id: UUID,
    body: BriefUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")

    update_data = body.model_dump(exclude_unset=True)
    if "lsi_keywords" in update_data and update_data["lsi_keywords"]:
        update_data["lsi_keywords"] = [kw.model_dump() if hasattr(kw, 'model_dump') else kw for kw in update_data["lsi_keywords"]]

    for field, value in update_data.items():
        setattr(brief, field, value)

    await log_action(db, user.id, "brief.update", "brief", brief.id)
    return brief


@router.delete("/briefs/{brief_id}")
async def archive_brief(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")

    brief.status = "draft"  # Reset to draft (soft archive)
    await log_action(db, user.id, "brief.archive", "brief", brief.id)
    return {"message": "Brief archived"}


# ── Pipeline ──

@router.post("/briefs/{brief_id}/research")
async def start_research(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")

    brief.status = "researching"
    # TODO: Dispatch Celery task
    # from app.tasks.research import run_research
    # run_research.delay(str(brief.id))

    await log_action(db, user.id, "research.start", "brief", brief.id)
    return {"message": "Research started", "brief_id": str(brief.id)}


@router.get("/briefs/{brief_id}/research", response_model=List[ResearchNoteResponse])
async def get_research(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    result = await db.execute(
        select(ResearchNote).where(ResearchNote.brief_id == brief_id).order_by(ResearchNote.fetched_at.desc())
    )
    return result.scalars().all()


@router.post("/briefs/{brief_id}/outline")
async def generate_outline(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    # TODO: Dispatch outline generation Celery task
    await log_action(db, user.id, "outline.generate", "brief", brief_id)
    return {"message": "Outline generation started"}


@router.put("/briefs/{brief_id}/outline")
async def update_outline(
    brief_id: UUID,
    sections: List[dict],  # [{heading, heading_level, sort_order, keyword_targets}]
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    # TODO: Update content_sections with new outline structure
    return {"message": "Outline updated"}


@router.post("/briefs/{brief_id}/write")
async def start_writing(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")

    brief.status = "writing"
    # TODO: Dispatch section-by-section writing Celery task
    # from app.tasks.writer import write_content
    # write_content.delay(str(brief.id))

    await log_action(db, user.id, "write.start", "brief", brief.id)
    return {"message": "Writing started", "brief_id": str(brief.id)}


# ── Sections ──

@router.get("/briefs/{brief_id}/sections", response_model=List[SectionResponse])
async def get_sections(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    result = await db.execute(
        select(ContentSection)
        .where(ContentSection.brief_id == brief_id)
        .order_by(ContentSection.sort_order)
    )
    return result.scalars().all()


@router.post("/sections/{section_id}/revise", response_model=SectionResponse)
async def revise_section(
    section_id: UUID,
    body: RevisionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    result = await db.execute(select(ContentSection).where(ContentSection.id == section_id))
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    # Save current version to history
    version = SectionVersion(
        section_id=section.id,
        version=section.version,
        content=section.content or "",
        revision_instruction=body.instruction,
    )
    db.add(version)

    # TODO: Call LLM for revision
    # Increment version
    section.version += 1

    await log_action(db, user.id, "section.revise", "content_section", section.id,
                     details={"instruction": body.instruction})
    return section


@router.get("/sections/{section_id}/versions")
async def get_section_versions(
    section_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    result = await db.execute(
        select(SectionVersion)
        .where(SectionVersion.section_id == section_id)
        .order_by(SectionVersion.version.desc())
    )
    return result.scalars().all()


# ── Validation & Plagiarism ──

@router.post("/briefs/{brief_id}/validate", response_model=ValidationResponse)
async def validate_brief(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    # TODO: Run SEO validation engine
    validation = ValidationResult(
        brief_id=brief_id,
        checks=[],
        overall_score=0,
    )
    db.add(validation)
    await db.flush()

    await log_action(db, user.id, "validation.run", "brief", brief_id)
    return validation


@router.post("/briefs/{brief_id}/plagiarism-check")
async def check_plagiarism(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    # TODO: Dispatch Copyscape + internal dedup check
    await log_action(db, user.id, "plagiarism.check", "brief", brief_id)
    return {"message": "Plagiarism check started"}


# ── Export ──

@router.get("/briefs/{brief_id}/export/{format}")
async def export_brief(
    brief_id: UUID,
    format: str,  # html, markdown, docx
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_viewer),
):
    if format not in ("html", "markdown", "docx"):
        raise HTTPException(status_code=400, detail="Format must be html, markdown, or docx")

    # TODO: Generate export
    return {"message": f"Export as {format} queued"}
