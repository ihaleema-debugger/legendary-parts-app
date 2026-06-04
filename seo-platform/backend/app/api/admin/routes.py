"""
Admin API routers: users, API keys, audit log, jobs, billing, system settings, database.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, AuditLog, ApiKeyVault, SystemSetting, UsageLog, CrawlJob
from app.schemas import (
    UserResponse, UserUpdate, InviteRequest,
    ApiKeyCreate, ApiKeyResponse,
    AuditLogResponse, UsageStatsResponse,
    SystemSettingUpdate, SystemHealthResponse,
)
from app.middleware.auth import require_admin, hash_password
from app.middleware.audit import log_action
from app.config import get_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])
settings = get_settings()

# ═══════════════════════════════════════════════
# USER MANAGEMENT
# ═══════════════════════════════════════════════

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("/users/invite", response_model=UserResponse)
async def invite_user(
    body: InviteRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user with temporary password (they'll reset via email)
    import secrets
    temp_password = secrets.token_urlsafe(16)

    user = User(
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(temp_password),
        role=body.role,
    )
    db.add(user)
    await db.flush()

    # TODO: Send invite email with temp password or reset link
    await log_action(db, admin.id, "user.invite", "user", user.id,
                     details={"email": body.email, "role": body.role})
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_values = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        old_values[field] = getattr(user, field)
        setattr(user, field, value)

    await log_action(db, admin.id, "user.update", "user", user.id,
                     details={"old": old_values, "new": body.model_dump(exclude_unset=True)})
    return user


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await log_action(db, admin.id, "user.deactivate", "user", user.id)
    return {"message": "User deactivated"}


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # TODO: Send password reset email
    await log_action(db, admin.id, "user.password_reset", "user", user.id)
    return {"message": "Password reset email sent"}


# ═══════════════════════════════════════════════
# API KEY VAULT
# ═══════════════════════════════════════════════

@router.get("/api-keys", response_model=List[ApiKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(ApiKeyVault).order_by(ApiKeyVault.service))
    keys = result.scalars().all()
    return [
        ApiKeyResponse(
            service=k.service,
            masked_key=f"{k.encrypted_key[:8]}...{k.encrypted_key[-4:]}" if len(k.encrypted_key) > 12 else "****",
            is_active=k.is_active,
            last_rotated_at=k.last_rotated_at,
        )
        for k in keys
    ]


@router.post("/api-keys", response_model=ApiKeyResponse)
async def upsert_api_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # TODO: Encrypt key with AES-256-GCM before storing
    # For now, storing with basic obfuscation (replace with real encryption)
    from cryptography.fernet import Fernet
    import base64, hashlib
    key_bytes = hashlib.sha256(settings.secret_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    f = Fernet(fernet_key)
    encrypted = f.encrypt(body.key.encode()).decode()

    result = await db.execute(select(ApiKeyVault).where(ApiKeyVault.service == body.service))
    existing = result.scalar_one_or_none()

    if existing:
        existing.encrypted_key = encrypted
        existing.is_active = True
        existing.last_rotated_at = datetime.now(timezone.utc)
        existing.updated_by = admin.id
        action = "api_key.rotate"
    else:
        vault_entry = ApiKeyVault(
            service=body.service,
            encrypted_key=encrypted,
            last_rotated_at=datetime.now(timezone.utc),
            updated_by=admin.id,
        )
        db.add(vault_entry)
        action = "api_key.create"

    await log_action(db, admin.id, action, "api_key", None,
                     details={"service": body.service})

    return ApiKeyResponse(
        service=body.service,
        masked_key=f"{body.key[:8]}...{body.key[-4:]}" if len(body.key) > 12 else "****",
        is_active=True,
        last_rotated_at=datetime.now(timezone.utc),
    )


@router.delete("/api-keys/{service}")
async def deactivate_api_key(
    service: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(ApiKeyVault).where(ApiKeyVault.service == service))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = False
    await log_action(db, admin.id, "api_key.deactivate", "api_key", None,
                     details={"service": service})
    return {"message": f"API key for {service} deactivated"}


# ═══════════════════════════════════════════════
# USAGE & BILLING
# ═══════════════════════════════════════════════

@router.get("/usage")
async def get_usage_stats(
    service: Optional[str] = None,
    module: Optional[str] = None,
    days: int = Query(default=30, le=365),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(
        UsageLog.service,
        func.count(UsageLog.id).label("total_calls"),
        func.sum(UsageLog.tokens_in).label("total_tokens_in"),
        func.sum(UsageLog.tokens_out).label("total_tokens_out"),
        func.sum(UsageLog.estimated_cost).label("total_cost"),
    ).where(UsageLog.created_at >= cutoff).group_by(UsageLog.service)

    if service:
        q = q.where(UsageLog.service == service)
    if module:
        q = q.where(UsageLog.module == module)

    result = await db.execute(q)
    rows = result.all()

    return [
        {
            "service": row.service,
            "total_calls": row.total_calls or 0,
            "total_tokens_in": row.total_tokens_in or 0,
            "total_tokens_out": row.total_tokens_out or 0,
            "total_cost": float(row.total_cost or 0),
            "period": f"last_{days}_days",
        }
        for row in rows
    ]


@router.get("/usage/breakdown")
async def get_usage_breakdown(
    days: int = Query(default=30, le=365),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Per-user breakdown
    q = select(
        UsageLog.user_id,
        User.full_name,
        User.email,
        UsageLog.module,
        func.sum(UsageLog.estimated_cost).label("total_cost"),
        func.count(UsageLog.id).label("total_calls"),
    ).join(User, User.id == UsageLog.user_id, isouter=True
    ).where(UsageLog.created_at >= cutoff
    ).group_by(UsageLog.user_id, User.full_name, User.email, UsageLog.module)

    result = await db.execute(q)
    rows = result.all()

    return [
        {
            "user_id": str(row.user_id) if row.user_id else None,
            "user_name": row.full_name or "System",
            "user_email": row.email,
            "module": row.module,
            "total_cost": float(row.total_cost or 0),
            "total_calls": row.total_calls or 0,
        }
        for row in rows
    ]


# ═══════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════

@router.get("/audit-log")
async def get_audit_log(
    user_id: Optional[UUID] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = select(AuditLog, User.email.label("user_email")).join(
        User, User.id == AuditLog.user_id, isouter=True
    )

    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)

    q = q.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.all()

    return [
        {
            "id": str(row.AuditLog.id),
            "user_id": str(row.AuditLog.user_id) if row.AuditLog.user_id else None,
            "user_email": row.user_email,
            "action": row.AuditLog.action,
            "resource_type": row.AuditLog.resource_type,
            "resource_id": str(row.AuditLog.resource_id) if row.AuditLog.resource_id else None,
            "details": row.AuditLog.details,
            "ip_address": str(row.AuditLog.ip_address) if row.AuditLog.ip_address else None,
            "created_at": row.AuditLog.created_at.isoformat(),
        }
        for row in rows
    ]


# ═══════════════════════════════════════════════
# JOB QUEUE MONITOR
# ═══════════════════════════════════════════════

@router.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """List Celery jobs (crawl jobs as proxy — full Celery inspect in future)."""
    q = select(CrawlJob)
    if status:
        q = q.where(CrawlJob.status == status)
    if job_type:
        q = q.where(CrawlJob.job_type == job_type)
    q = q.order_by(CrawlJob.created_at.desc()).limit(limit)
    result = await db.execute(q)
    jobs = result.scalars().all()

    return [
        {
            "id": str(j.id),
            "type": j.job_type,
            "status": j.status,
            "target": j.target_domain,
            "progress": f"{j.pages_crawled}/{j.pages_total or '?'}",
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(CrawlJob).where(CrawlJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = "queued"
    job.pages_crawled = 0
    # TODO: Re-dispatch Celery task

    await log_action(db, admin.id, "job.retry", "crawl_job", job.id)
    return {"message": "Job re-queued"}


@router.post("/jobs/{job_id}/kill")
async def kill_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(CrawlJob).where(CrawlJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = "failed"
    # TODO: Revoke Celery task

    await log_action(db, admin.id, "job.kill", "crawl_job", job.id)
    return {"message": "Job killed"}


# ═══════════════════════════════════════════════
# SYSTEM SETTINGS
# ═══════════════════════════════════════════════

@router.get("/system/settings")
async def get_system_settings(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = select(SystemSetting)
    if category:
        q = q.where(SystemSetting.category == category)
    q = q.order_by(SystemSetting.category, SystemSetting.key)
    result = await db.execute(q)
    settings_list = result.scalars().all()

    return [
        {
            "key": s.key,
            "value": s.value,
            "category": s.category,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in settings_list
    ]


@router.put("/system/settings/{key}")
async def update_system_setting(
    key: str,
    body: SystemSettingUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")

    old_value = setting.value
    setting.value = body.value
    setting.updated_by = admin.id

    await log_action(db, admin.id, "settings.update", "system_setting", None,
                     details={"key": key, "old": old_value, "new": body.value})
    return {"key": key, "value": body.value, "message": "Setting updated"}


# ═══════════════════════════════════════════════
# SYSTEM HEALTH
# ═══════════════════════════════════════════════

@router.get("/system/health", response_model=SystemHealthResponse)
async def system_health(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    import time
    start = time.time()

    # DB check
    try:
        await db.execute(select(func.now()))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    # Redis check
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url)
        r.ping()
        redis_status = "healthy"
    except Exception:
        redis_status = "unhealthy"

    # Celery check
    try:
        from app.tasks.worker import celery_app
        inspect = celery_app.control.inspect()
        active = inspect.active() or {}
        worker_count = len(active)
        active_tasks = sum(len(tasks) for tasks in active.values())
    except Exception:
        worker_count = 0
        active_tasks = 0

    # Queued jobs
    queued = await db.execute(
        select(func.count(CrawlJob.id)).where(CrawlJob.status == "queued")
    )

    return SystemHealthResponse(
        status="healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded",
        uptime_seconds=time.time() - start,  # Placeholder — use process start time in prod
        database=db_status,
        redis=redis_status,
        celery_workers=worker_count,
        active_jobs=active_tasks,
        queued_jobs=queued.scalar() or 0,
    )


# ═══════════════════════════════════════════════
# DATABASE MANAGEMENT
# ═══════════════════════════════════════════════

@router.post("/database/backup")
async def trigger_backup(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # TODO: Trigger pg_dump via subprocess or Celery task
    await log_action(db, admin.id, "backup.trigger")
    return {"message": "Database backup started"}


@router.get("/database/backups")
async def list_backups(
    admin: User = Depends(require_admin),
):
    # TODO: List backup files from storage
    return {"backups": [], "message": "Backup listing not yet implemented"}


@router.post("/database/prune")
async def prune_data(
    confirm: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass ?confirm=true to confirm data pruning")

    # TODO: Prune stale crawl data, expired Semrush cache, orphaned notes
    await log_action(db, admin.id, "data.prune")
    return {"message": "Data pruning started"}
