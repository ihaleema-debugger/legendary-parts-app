"""
Application configuration loaded from environment variables.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ──
    app_name: str = "SEO Platform"
    debug: bool = False

    # ── Database ──
    database_url: str = "postgresql+asyncpg://seoplatform:password@postgres:5432/seoplatform"

    # ── Redis ──
    redis_url: str = "redis://redis:6379/0"

    # ── Auth ──
    secret_key: str = "CHANGE-ME"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ── LLM Providers ──
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    mistral_api_key: str = ""

    # ── SEO Data ──
    semrush_api_key: str = ""

    # ── Web Research ──
    serpapi_key: str = ""

    # ── Plagiarism ──
    copyscape_api_key: str = ""

    # ── Email ──
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@legendary-parts.com"

    # ── Domain ──
    domain: str = "seo.legendary-parts.com"
    frontend_url: str = "https://seo.legendary-parts.com"

    # ── First Admin ──
    first_admin_email: str = "admin@legendary-parts.com"
    first_admin_password: str = "CHANGE-ME"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
