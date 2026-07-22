import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Campaign, CampaignStatus, ScheduledTask
from app.services.campaign_service import execute_campaign
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3, name="app.tasks.campaign_tasks.send_campaign")
def send_campaign(self, campaign_id: int):
    with SessionLocal() as db:
        task = db.scalar(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign_id).order_by(ScheduledTask.created_at.desc()))
        if task:
            task.status, task.attempts = "running", self.request.retries + 1
            db.commit()
        try:
            result = asyncio.run(execute_campaign(db, campaign_id))
            if task:
                task.status, task.result = "completed", result
                db.commit()
            return result
        except Exception as exc:
            if task:
                task.status, task.error_message = "failed", str(exc)[:1000]
                db.commit()
            raise


@celery_app.task(name="app.tasks.campaign_tasks.dispatch_due")
def dispatch_due():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        campaigns = db.scalars(select(Campaign).where(Campaign.status == CampaignStatus.scheduled, Campaign.scheduled_at <= now)).all()
        for campaign in campaigns:
            campaign.status = CampaignStatus.sending
            result = send_campaign.delay(campaign.id)
            task = db.scalar(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign.id, ScheduledTask.status == "pending").order_by(ScheduledTask.created_at.desc()))
            if task:
                task.celery_task_id, task.status = result.id, "queued"
        db.commit()
        return {"dispatched": len(campaigns)}
