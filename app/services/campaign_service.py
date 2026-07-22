import asyncio
import hashlib
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    Campaign, CampaignChannel, CampaignRecipient, CampaignStatus, Channel, Contact, ContactList,
    DeliveryEvent, MessageTemplate,
)
from app.services.consent_service import has_valid_consent
from app.services.exceptions import IntegrationError
from app.services.facebook_service import facebook_service
from app.services.instagram_service import instagram_service
from app.services.rate_limit_service import check_company_limits
from app.services.tracking_service import make_tracking_url
from app.services.whatsapp_service import whatsapp_service


def validate_whatsapp_readiness(db: Session, company_id: int, contact_list_id: int | None) -> dict:
    if not contact_list_id:
        return {"ready": False, "reason": "Selecione uma lista de contatos para a campanha de WhatsApp."}
    contact_list = db.scalar(select(ContactList).where(ContactList.id == contact_list_id, ContactList.company_id == company_id))
    if not contact_list:
        return {"ready": False, "reason": "Lista de contatos não encontrada."}
    contacts = db.scalars(
        select(Contact)
        .join(Contact.lists)
        .where(ContactList.id == contact_list_id, Contact.company_id == company_id)
        .options(selectinload(Contact.consents))
    ).unique().all()
    eligible = [contact for contact in contacts if has_valid_consent(db, contact, Channel.whatsapp)]
    if not contacts:
        return {"ready": False, "reason": "A lista selecionada está vazia."}
    if not eligible:
        return {"ready": False, "reason": "A lista não possui contatos ativos com consentimento válido para WhatsApp."}
    template = db.scalar(select(MessageTemplate).where(MessageTemplate.company_id == company_id, MessageTemplate.status == "approved"))
    simulation = settings.simulation_mode and not whatsapp_service.configured
    if not simulation and not whatsapp_service.configured:
        return {"ready": False, "reason": "Configure as credenciais oficiais do WhatsApp Business antes de criar a campanha."}
    if not simulation and not template:
        return {"ready": False, "reason": "Cadastre ou sincronize um template de WhatsApp aprovado pela Meta."}
    if template and not any(word in template.body.casefold() for word in ("sair", "parar", "cancel")):
        return {"ready": False, "reason": "O template aprovado precisa informar claramente como cancelar o recebimento."}
    return {
        "ready": True,
        "eligible_contacts": len(eligible),
        "blocked_contacts": len(contacts) - len(eligible),
        "simulation": simulation,
        "template": template,
    }


def materialize_recipients(db: Session, campaign: Campaign) -> int:
    if campaign.channel != Channel.whatsapp or not campaign.contact_list_id:
        return 0
    contacts = db.scalars(
        select(Contact)
        .join(Contact.lists)
        .where(ContactList.id == campaign.contact_list_id, Contact.company_id == campaign.company_id)
        .options(selectinload(Contact.consents))
    ).unique().all()
    existing = set(db.scalars(select(CampaignRecipient.contact_id).where(CampaignRecipient.campaign_id == campaign.id)).all())
    for contact in contacts:
        if contact.id not in existing and has_valid_consent(db, contact, campaign.channel):
            day = datetime.now(timezone.utc).date().isoformat()
            key = hashlib.sha256(f"{campaign.company_id}:{contact.id}:{campaign.channel.value}:{campaign.title}:{campaign.body}:{campaign.link_url}:{day}".encode()).hexdigest()
            if not db.scalar(select(CampaignRecipient.id).where(CampaignRecipient.idempotency_key == key)):
                db.add(CampaignRecipient(campaign_id=campaign.id, contact_id=contact.id, idempotency_key=key))
    db.flush()
    return db.scalar(select(func.count(CampaignRecipient.id)).where(CampaignRecipient.campaign_id == campaign.id)) or 0


async def execute_campaign(db: Session, campaign_id: int) -> dict:
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if not campaign or campaign.status in {CampaignStatus.cancelled, CampaignStatus.sent}:
        return {"status": "ignored", "reason": "Campanha inexistente, cancelada ou já concluída."}
    allowed, reason = check_company_limits(db, campaign.company_id)
    if not allowed:
        campaign.status = CampaignStatus.failed
        db.commit()
        return {"status": "paused", "reason": reason}
    campaign.status = CampaignStatus.sending
    db.commit()
    if campaign.channel == Channel.facebook:
        tracked_link = make_tracking_url(campaign.id) if campaign.link_url else None
        result = await facebook_service.publish(campaign.body, tracked_link, campaign.image_path, campaign.video_path)
        db.add(CampaignChannel(campaign_id=campaign.id, channel=campaign.channel, external_id=result.external_id, status="published" if result.success else "simulated"))
        campaign.status = CampaignStatus.sent if result.success else CampaignStatus.failed
        db.commit()
        return {"status": "sent" if result.success else "simulation", "message": result.error}
    if campaign.channel == Channel.instagram:
        media_url = campaign.video_path or campaign.image_path
        if not media_url or not media_url.startswith("http"):
            campaign.status = CampaignStatus.failed
            db.commit()
            return {"status": "failed", "reason": "Instagram requer uma URL pública HTTPS para a imagem."}
        result = await instagram_service.publish_media(media_url, campaign.body, is_video=bool(campaign.video_path))
        db.add(CampaignChannel(campaign_id=campaign.id, channel=campaign.channel, external_id=result.external_id, status="published" if result.success else "simulated"))
        campaign.status = CampaignStatus.sent if result.success else CampaignStatus.failed
        db.commit()
        return {"status": "sent" if result.success else "simulation", "message": result.error}
    recipient_count = materialize_recipients(db, campaign)
    if recipient_count > settings.large_campaign_threshold and not campaign.approved_at:
        campaign.status = CampaignStatus.review
        campaign.requires_confirmation = True
        db.commit()
        return {"status": "review", "reason": "Confirmação adicional obrigatória para campanha grande."}
    readiness = validate_whatsapp_readiness(db, campaign.company_id, campaign.contact_list_id)
    if not readiness["ready"]:
        campaign.status = CampaignStatus.failed
        db.commit()
        return {"status": "failed", "reason": readiness["reason"]}
    template = readiness["template"]
    recipients = db.scalars(
        select(CampaignRecipient)
        .where(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "pending")
        .options(selectinload(CampaignRecipient.contact))
    ).all()
    sent = failed = simulated = 0
    for recipient in recipients:
        if not has_valid_consent(db, recipient.contact, Channel.whatsapp):
            recipient.status, recipient.error_message = "blocked", "Contato sem consentimento válido."
            failed += 1
            continue
        try:
            template_name = template.name if template else "simulation_only"
            template_language = template.language if template else "pt_BR"
            result = await whatsapp_service.send_template(recipient.contact.phone, template_name, template_language)
            if result.success:
                recipient.status, recipient.external_message_id = "sent", result.external_id
                sent += 1
            else:
                recipient.status, recipient.error_message = "simulated", result.error
                simulated += 1
            db.add(DeliveryEvent(campaign_id=campaign.id, recipient_id=recipient.id, external_id=result.external_id, event_type=recipient.status, payload={"simulated": result.simulated}))
            if result.success and settings.minute_message_limit > 0:
                await asyncio.sleep(60 / settings.minute_message_limit)
        except IntegrationError as exc:
            recipient.status, recipient.error_message = "failed", str(exc)
            failed += 1
    if simulated and not sent and not failed:
        campaign.status = CampaignStatus.simulated
    else:
        campaign.status = CampaignStatus.sent if sent and not failed else CampaignStatus.failed
    db.commit()
    return {"status": campaign.status.value, "sent": sent, "failed": failed, "simulated": simulated}
