"""
SEO Platform — FastAPI Application Entry Point

Mounts all routers, configures middleware, and handles startup events.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import get_settings
from app.database import engine, async_session, Base
from app.models import User
from app.middleware.auth import hash_password

# Import routers
from app.api.shared.auth import router as auth_router
from app.api.shared.routes import router as shared_router
from app.api.keygap.routes import router as keygap_router
from app.api.inkwell.routes import router as inkwell_router
from app.api.admin.routes import router as admin_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # ── Startup ──
    # Create first admin user if none exists
    async with async_session() as db:
        result = await db.execute(select(User).where(User.role == "admin"))
        if not result.scalar_one_or_none():
            admin = User(
                email=settings.first_admin_email,
                full_name="Platform Admin",
                hashed_password=hash_password(settings.first_admin_password),
                role="admin",
            )
            db.add(admin)
            await db.commit()
            print(f"✓ Created first admin user: {settings.first_admin_email}")
        else:
            print("✓ Admin user exists")

    print("✓ SEO Platform API started")
    yield

    # ── Shutdown ──
    await engine.dispose()
    print("✓ SEO Platform API stopped")


# ── App ──
app = FastAPI(
    title="SEO Platform API",
    description="KeyGap + Inkwell — Unified SEO Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Prometheus (optional) ──
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")
except ImportError:
    pass

# ── Mount Routers ──
app.include_router(auth_router)
app.include_router(shared_router)
app.include_router(keygap_router)
app.include_router(inkwell_router)
app.include_router(admin_router)
