"""
Authentication endpoints: login, register, refresh, password reset.
"""

from datetime import datetime, timezone
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, RefreshToken
from app.schemas import (
    LoginRequest, TokenResponse, RefreshRequest,
    UserCreate, UserMe, PasswordResetRequest, PasswordReset
)
from app.middleware.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user
)
from app.middleware.audit import log_action
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        await log_action(db, None, "user.failed_login", details={"email": body.email},
                         ip_address=request.client.host if request.client else None)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)

    # Generate tokens
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id))

    # Store refresh token hash
    token_hash = sha256(refresh.encode()).hexdigest()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc).replace(day=datetime.now(timezone.utc).day + settings.refresh_token_expire_days),
    )
    db.add(rt)

    await log_action(db, user.id, "user.login",
                     ip_address=request.client.host if request.client else None)

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=UserMe)
async def register(body: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Register a new user. In production, this should be admin-only (use /api/admin/users/invite)."""
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()

    await log_action(db, user.id, "user.register", resource_type="user", resource_id=user.id,
                     ip_address=request.client.host if request.client else None)

    return user


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    token_hash = sha256(body.refresh_token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
        )
    )
    stored = result.scalar_one_or_none()
    if not stored:
        raise HTTPException(status_code=401, detail="Token revoked or not found")

    # Revoke old token
    stored.revoked = True

    # Get user
    user_result = await db.execute(select(User).where(User.id == stored.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Issue new tokens
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id))

    new_hash = sha256(refresh.encode()).hexdigest()
    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        expires_at=datetime.now(timezone.utc).replace(day=datetime.now(timezone.utc).day + settings.refresh_token_expire_days),
    )
    db.add(new_rt)

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserMe)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password")
async def forgot_password(body: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """Send password reset email. Always returns 200 to prevent email enumeration."""
    # TODO: Implement email sending with reset token
    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: PasswordReset, db: AsyncSession = Depends(get_db)):
    """Reset password with token from email."""
    # TODO: Implement token verification and password update
    return {"message": "Password has been reset."}
