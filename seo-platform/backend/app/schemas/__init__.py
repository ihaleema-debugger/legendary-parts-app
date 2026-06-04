"""
Pydantic schemas for request/response validation.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


# ═══════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8)
    role: str = "viewer"

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class UserMe(UserResponse):
    pass

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordReset(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


# ═══════════════════════════════════════════════
# KEYGAP
# ═══════════════════════════════════════════════

class ProjectCreate(BaseModel):
    name: str
    main_domain: str = "legendary-parts.com"
    competitor_domains: List[str] = []

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    competitor_domains: Optional[List[str]] = None
    status: Optional[str] = None

class ProjectResponse(BaseModel):
    id: UUID
    name: str
    main_domain: str
    competitor_domains: List[str]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CrawlCreate(BaseModel):
    project_id: UUID
    target_domain: str
    job_type: str = "competitor_crawl"
    config: dict = {}

class CrawlResponse(BaseModel):
    id: UUID
    project_id: UUID
    target_domain: str
    job_type: str
    status: str
    pages_crawled: int
    pages_total: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class KeywordResponse(BaseModel):
    id: UUID
    keyword: str
    category: str
    source: str
    domain: Optional[str] = None
    extraction_method: Optional[str] = None
    confidence: Optional[float] = None

    class Config:
        from_attributes = True

class GapResultResponse(BaseModel):
    id: UUID
    project_id: UUID
    keyword: str
    category: Optional[str] = None
    competitor_domains: List[str] = []
    opportunity_score: Optional[float] = None
    suggested_content_type: Optional[str] = None
    suggestion_detail: Optional[str] = None
    brief_id: Optional[UUID] = None

    class Config:
        from_attributes = True

class IndexStatusResponse(BaseModel):
    total_keywords: int
    total_pages: int
    last_indexed_at: Optional[datetime] = None
    status: str


# ═══════════════════════════════════════════════
# INKWELL
# ═══════════════════════════════════════════════

class LSIKeyword(BaseModel):
    keyword: str
    min_count: int = 1

class BriefCreate(BaseModel):
    title: str
    primary_keyword: str
    lsi_keywords: List[LSIKeyword] = []
    keyword_instructions: Optional[str] = None
    seo_instructions: Optional[str] = None
    target_word_count: int = 2500
    style_guide: Optional[str] = None
    llm_model: str = "claude-sonnet-4"
    research_depth: str = "standard"
    reference_style: str = "inline"
    gap_result_id: Optional[UUID] = None

class BriefUpdate(BaseModel):
    title: Optional[str] = None
    primary_keyword: Optional[str] = None
    lsi_keywords: Optional[List[LSIKeyword]] = None
    keyword_instructions: Optional[str] = None
    seo_instructions: Optional[str] = None
    target_word_count: Optional[int] = None
    style_guide: Optional[str] = None
    llm_model: Optional[str] = None
    research_depth: Optional[str] = None
    reference_style: Optional[str] = None
    status: Optional[str] = None

class BriefResponse(BaseModel):
    id: UUID
    title: str
    primary_keyword: str
    lsi_keywords: list
    keyword_instructions: Optional[str] = None
    seo_instructions: Optional[str] = None
    target_word_count: int
    style_guide: Optional[str] = None
    llm_model: str
    research_depth: str
    reference_style: str
    status: str
    gap_result_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SectionResponse(BaseModel):
    id: UUID
    brief_id: UUID
    heading: str
    heading_level: int
    content: Optional[str] = None
    sort_order: int
    version: int
    keyword_targets: list = []

    class Config:
        from_attributes = True

class RevisionRequest(BaseModel):
    instruction: str

class ResearchNoteResponse(BaseModel):
    id: UUID
    source_url: str
    source_title: Optional[str] = None
    source_domain: Optional[str] = None
    summary: Optional[str] = None
    is_authority: bool
    fetched_at: datetime

    class Config:
        from_attributes = True

class ValidationResponse(BaseModel):
    id: UUID
    brief_id: UUID
    checks: list
    overall_score: Optional[float] = None
    plagiarism_result: Optional[dict] = None
    validated_at: datetime

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════
# ADMIN
# ═══════════════════════════════════════════════

class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str = "editor"

class ApiKeyCreate(BaseModel):
    service: str
    key: str

class ApiKeyResponse(BaseModel):
    service: str
    masked_key: str
    is_active: bool
    last_rotated_at: Optional[datetime] = None

class AuditLogResponse(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[UUID] = None
    details: dict = {}
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class UsageStatsResponse(BaseModel):
    service: str
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost: float
    period: str

class SystemSettingUpdate(BaseModel):
    value: str | int | float | bool | dict | list

class SystemHealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    database: str
    redis: str
    celery_workers: int
    active_jobs: int
    queued_jobs: int

class DashboardStatsResponse(BaseModel):
    active_projects: int
    running_crawls: int
    active_briefs: int
    published_content: int
    total_gap_keywords: int
    monthly_cost_estimate: float


# ═══════════════════════════════════════════════
# BRIDGE
# ═══════════════════════════════════════════════

class CreateBriefFromGapRequest(BaseModel):
    gap_result_id: UUID
    title: Optional[str] = None
    target_word_count: int = 2500
    llm_model: str = "claude-sonnet-4"
    style_guide: Optional[str] = None
