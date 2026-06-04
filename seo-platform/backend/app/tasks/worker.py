"""
Celery worker configuration and task registration.
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "seo_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,  # 24 hours
)

# Scheduled tasks
celery_app.conf.beat_schedule = {
    "weekly-reindex": {
        "task": "app.tasks.crawl.reindex_main_site",
        "schedule": crontab(hour=2, minute=0, day_of_week=1),  # Monday 2am
    },
    "daily-backup": {
        "task": "app.tasks.maintenance.backup_database",
        "schedule": crontab(hour=3, minute=0),  # 3am daily
    },
    "daily-cache-cleanup": {
        "task": "app.tasks.maintenance.cleanup_expired_cache",
        "schedule": crontab(hour=4, minute=0),  # 4am daily
    },
}

# Auto-discover tasks
celery_app.autodiscover_tasks([
    "app.tasks.crawl",
    "app.tasks.research",
    "app.tasks.writer",
    "app.tasks.validation",
    "app.tasks.plagiarism",
    "app.tasks.maintenance",
])
