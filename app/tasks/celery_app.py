from celery import Celery

from app.config import settings

celery_app = Celery("divulgai", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    timezone="America/Sao_Paulo",
    enable_utc=True,
    task_track_started=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={"dispatch-due-campaigns": {"task": "app.tasks.campaign_tasks.dispatch_due", "schedule": 60.0}},
    imports=("app.tasks.campaign_tasks",),
)
celery_app.autodiscover_tasks(["app.tasks"])
