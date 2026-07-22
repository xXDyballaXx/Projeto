from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Campaign, CampaignRecipient, Company


def check_company_limits(db: Session, company_id: int) -> tuple[bool, str | None]:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = db.scalar(
        select(func.count(CampaignRecipient.id))
        .join(Campaign)
        .where(
            Campaign.company_id == company_id,
            CampaignRecipient.status.in_(["sending", "sent", "delivered", "read"]),
            CampaignRecipient.updated_at >= day_start,
        )
    ) or 0
    company_limit = db.scalar(select(Company.daily_limit).where(Company.id == company_id)) or settings.daily_message_limit
    if sent_today >= min(company_limit, settings.daily_message_limit):
        return False, "Limite diário de mensagens atingido."
    sent_last_hour = db.scalar(
        select(func.count(CampaignRecipient.id)).join(Campaign).where(
            Campaign.company_id == company_id,
            CampaignRecipient.status.in_(["sending", "sent", "delivered", "read"]),
            CampaignRecipient.updated_at >= now - timedelta(hours=1),
        )
    ) or 0
    if sent_last_hour >= settings.hourly_message_limit:
        return False, "Limite de mensagens por hora atingido."
    sent_last_minute = db.scalar(
        select(func.count(CampaignRecipient.id)).join(Campaign).where(
            Campaign.company_id == company_id,
            CampaignRecipient.status.in_(["sending", "sent", "delivered", "read"]),
            CampaignRecipient.updated_at >= now - timedelta(minutes=1),
        )
    ) or 0
    if sent_last_minute >= settings.minute_message_limit:
        return False, "Limite de mensagens por minuto atingido."
    recent_failures = db.scalar(
        select(func.count(CampaignRecipient.id))
        .join(Campaign)
        .where(
            Campaign.company_id == company_id,
            CampaignRecipient.status == "failed",
            CampaignRecipient.updated_at >= now - timedelta(minutes=10),
        )
    ) or 0
    recent_total = db.scalar(
        select(func.count(CampaignRecipient.id))
        .join(Campaign)
        .where(Campaign.company_id == company_id, CampaignRecipient.updated_at >= now - timedelta(minutes=10))
    ) or 0
    if recent_total >= 10 and recent_failures / recent_total >= 0.5:
        return False, "Envios pausados devido à taxa elevada de erros."
    return True, None
