import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Campaign, CampaignStatus, ScheduledTask
from app.services.campaign_service import execute_campaign
from app.tasks.celery_app import celery_app

logger = logging.getLogger("divulgai.tasks")


@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError,),
    retry_backoff=True,
    max_retries=3,
    name="app.tasks.campaign_tasks.send_campaign",
)
def send_campaign(self, campaign_id: int, scheduled_task_id: str | None = None):
    with SessionLocal() as db:
        campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
        task = db.get(ScheduledTask, scheduled_task_id) if scheduled_task_id else db.scalars(
            select(ScheduledTask)
            .where(ScheduledTask.campaign_id == campaign_id)
            .order_by(ScheduledTask.created_at.desc())
        ).first()
        if not campaign or not task or task.campaign_id != campaign_id:
            return {"status": "ignored", "reason": "Campanha ou tarefa inexistente."}
        if task.status == "cancelled" or campaign.status == CampaignStatus.cancelled:
            task.status = "cancelled"
            db.commit()
            return {"status": "ignored", "reason": "Tarefa cancelada."}
        if task.status in {"running", "completed", "ignored", "review"}:
            return {"status": "ignored", "reason": "Esta tarefa já foi assumida ou concluída."}
        competing = db.scalar(
            select(ScheduledTask.id).where(
                ScheduledTask.campaign_id == campaign_id,
                ScheduledTask.id != task.id,
                ScheduledTask.status == "running",
            )
        )
        if competing:
            task.status = "cancelled"
            task.error_message = "Outra tarefa já assumiu o processamento desta campanha."
            db.commit()
            return {"status": "ignored", "reason": task.error_message}
        task.status = "running"
        task.attempts = max(task.attempts + 1, self.request.retries + 1)
        task.error_message = None
        db.commit()
        logger.info("Iniciando campanha campaign_id=%s task_id=%s attempt=%s", campaign_id, task.id, task.attempts)
        try:
            result = asyncio.run(execute_campaign(db, campaign_id))
            result_status = result.get("status")
            if result_status in {"sent", "simulated", "simulation"}:
                task.status = "completed"
            elif result_status == "ignored":
                task.status = "ignored"
            elif result_status == "review":
                task.status = "review"
            else:
                task.status = "failed"
                task.error_message = str(result.get("reason") or result.get("message") or "Falha no processamento.")[:1000]
            task.result = result
            db.commit()
            logger.info("Campanha finalizada campaign_id=%s task_id=%s status=%s", campaign_id, task.id, result_status)
            return result
        except Exception as exc:
            task.status, task.error_message = "failed", str(exc)[:1000]
            if campaign.status == CampaignStatus.sending:
                campaign.status = CampaignStatus.failed
            db.commit()
            logger.exception("Erro ao executar campanha campaign_id=%s task_id=%s", campaign_id, task.id)
            raise


@celery_app.task(name="app.tasks.campaign_tasks.dispatch_due")
def dispatch_due():
    now = datetime.now(timezone.utc)
    dispatched = 0
    with SessionLocal() as db:
        campaign_ids = db.scalars(
            select(Campaign.id)
            .where(Campaign.status == CampaignStatus.scheduled, Campaign.scheduled_at <= now)
            .order_by(Campaign.scheduled_at)
        ).all()
        for campaign_id in campaign_ids:
            campaign = db.scalar(
                select(Campaign)
                .where(Campaign.id == campaign_id, Campaign.status == CampaignStatus.scheduled)
                .with_for_update()
            )
            if not campaign:
                continue
            task = db.scalars(
                select(ScheduledTask)
                .where(ScheduledTask.campaign_id == campaign.id, ScheduledTask.status == "pending")
                .order_by(ScheduledTask.created_at.desc())
            ).first()
            if not task:
                task = ScheduledTask(
                    company_id=campaign.company_id,
                    campaign_id=campaign.id,
                    execute_at=campaign.scheduled_at or now,
                )
                db.add(task)
                db.flush()
            campaign.status = CampaignStatus.sending
            task.status = "queued"
            db.commit()
            try:
                result = send_campaign.delay(campaign.id, task.id)
            except Exception as exc:
                campaign.status = CampaignStatus.scheduled
                task.status = "failed"
                task.error_message = str(exc)[:1000]
                db.commit()
                logger.exception("Fila indisponível para campaign_id=%s", campaign.id)
                continue
            task.celery_task_id = result.id
            db.commit()
            dispatched += 1
    return {"dispatched": dispatched}


@celery_app.task(name="app.tasks.campaign_tasks.reconcile_stuck")
def reconcile_stuck():
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    reconciled = 0
    with SessionLocal() as db:
        campaigns = db.scalars(
            select(Campaign).where(Campaign.status == CampaignStatus.sending, Campaign.updated_at < cutoff)
        ).all()
        for campaign in campaigns:
            campaign.status = CampaignStatus.failed
            tasks = db.scalars(
                select(ScheduledTask).where(
                    ScheduledTask.campaign_id == campaign.id,
                    ScheduledTask.status.in_(["queued", "running"]),
                )
            ).all()
            for task in tasks:
                task.status = "failed"
                task.error_message = "Processamento interrompido; revise antes de tentar novamente."
            reconciled += 1
        db.commit()
    if reconciled:
        logger.warning("Campanhas presas reconciliadas count=%s", reconciled)
    return {"reconciled": reconciled}
