from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.database import get_db
from app.models import AuditLog, Campaign, CampaignChannel, CampaignRecipient, CampaignStatus, Contact, DeliveryEvent, User
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contacts = db.scalar(select(func.count(Contact.id)).where(Contact.company_id == user.company_id)) or 0
    campaigns = db.scalar(select(func.count(Campaign.id)).where(Campaign.company_id == user.company_id)) or 0
    scheduled = db.scalar(select(func.count(Campaign.id)).where(Campaign.company_id == user.company_id, Campaign.status == CampaignStatus.scheduled)) or 0
    sent_campaigns = db.scalar(select(func.count(Campaign.id)).where(Campaign.company_id == user.company_id, Campaign.status == CampaignStatus.sent)) or 0
    publications = db.scalar(
        select(func.count(CampaignChannel.id)).join(Campaign).where(
            Campaign.company_id == user.company_id, CampaignChannel.status == "published"
        )
    ) or 0
    clicks = db.scalar(
        select(func.count(DeliveryEvent.id)).join(Campaign, DeliveryEvent.campaign_id == Campaign.id).where(
            DeliveryEvent.event_type == "clicked", Campaign.company_id == user.company_id
        )
    ) or 0
    recipient_stats = db.execute(
        select(
            func.sum(case((CampaignRecipient.status.in_(["delivered", "read"]), 1), else_=0)),
            func.sum(case((CampaignRecipient.status.in_(["failed", "blocked"]), 1), else_=0)),
        ).join(Campaign).where(Campaign.company_id == user.company_id)
    ).one()
    activities = db.scalars(select(AuditLog).where(AuditLog.company_id == user.company_id).order_by(AuditLog.created_at.desc()).limit(8)).all()
    return {
        "totals": {"contacts": contacts, "campaigns": campaigns, "scheduled": scheduled, "sent_campaigns": sent_campaigns, "delivered": recipient_stats[0] or 0, "errors": recipient_stats[1] or 0, "publications": publications, "clicks": clicks},
        "chart": {"labels": ["Contatos", "Campanhas", "Agendadas", "Enviadas"], "values": [contacts, campaigns, scheduled, sent_campaigns]},
        "activities": [{"action": a.action, "date": a.created_at, "entity": a.entity_type} for a in activities],
    }
