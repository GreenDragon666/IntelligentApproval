"""Celery application configured for durable Redis-backed delivery."""

from celery import Celery

from ..config import get_settings


settings = get_settings()
celery_app = Celery("intelligent_approval", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    imports=("app.tasks.review_tasks",),
    task_default_queue="approval",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    broker_connection_retry_on_startup=True,
    timezone="Asia/Shanghai",
    enable_utc=True,
    beat_schedule={
        "recover-undispatched-reviews": {
            "task": "approval.requeue_queued_reviews",
            "schedule": float(settings.celery_requeue_interval_seconds),
        },
        "recover-stale-reviews": {
            "task": "approval.recover_stale_reviews",
            "schedule": float(settings.celery_stale_recovery_interval_seconds),
        },
    },
)
celery_app.autodiscover_tasks(["app.tasks"])
