from celery import Celery

from app.config import settings

celery_app = Celery("divulgai", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    timezone="America/Sao_Paulo",
    enable_utc=True,
    task_track_started=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=300,
    task_time_limit=330,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-due-campaigns": {"task": "app.tasks.campaign_tasks.dispatch_due", "schedule": 60.0},
        "reconcile-stuck-campaigns": {"task": "app.tasks.campaign_tasks.reconcile_stuck", "schedule": 300.0},
    },
    imports=("app.tasks.campaign_tasks",),
)
celery_app.autodiscover_tasks(["app.tasks"])
