"""Celery app and exam generation task."""

from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "curriculum_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_BROKER_URL,
    include=["app.tasks.exam_task", "app.tasks.document_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_extended=True,
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=7200,
    task_soft_time_limit=6600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_ignore_result=False,
    task_store_errors_even_if_ignored=True,
)
