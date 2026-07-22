import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    Campaign,
    CampaignChannel,
    CampaignRecipient,
    CampaignStatus,
    Channel,
    Contact,
    ContactList,
    DeliveryEvent,
    MessageTemplate,
)
from app.services.consent_service import has_valid_consent
from app.services.exceptions import IntegrationError
from app.services.facebook_service import facebook_service
from app.services.instagram_service import instagram_service
from app.services.integration_credentials import CompanyIntegration, load_company_integration
from app.services.rate_limit_service import check_company_limits
from app.services.tracking_service import make_tracking_url
from app.services.whatsapp_service import SendResult, whatsapp_service

logger = logging.getLogger("divulgai.campaigns")


def validate_whatsapp_readiness(
    db: Session,
    company_id: int,
    contact_list_id: int | None,
    message_template_id: int | None = None,
) -> dict:
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

    integration = load_company_integration(db, company_id, "whatsapp")
    simulation = settings.simulation_mode
    template = None
    if message_template_id:
        template = db.scalar(
            select(MessageTemplate).where(
                MessageTemplate.id == message_template_id,
                MessageTemplate.company_id == company_id,
                MessageTemplate.status == "approved",
            )
        )
        if not template:
            return {"ready": False, "reason": "O template selecionado não pertence à empresa ou ainda não foi aprovado pela Meta."}
    if not simulation:
        phone_number_id = integration.external_account_id
        access_token = integration.credentials.get("access_token")
        if not integration.active or not whatsapp_service.is_configured(phone_number_id, access_token):
            return {"ready": False, "reason": "Teste e ative as credenciais oficiais do WhatsApp Business antes de criar a campanha."}
        if not template:
            return {"ready": False, "reason": "Selecione um template de WhatsApp sincronizado e aprovado pela Meta."}
        if not re.search(r"\{\{\s*1\s*\}\}", template.body):
            return {"ready": False, "reason": "O template aprovado precisa possuir ao menos a variável {{1}} para o conteúdo revisado da campanha."}
    if template and not any(word in template.body.casefold() for word in ("sair", "parar", "cancel")):
        return {"ready": False, "reason": "O template aprovado precisa informar claramente como cancelar o recebimento."}
    return {
        "ready": True,
        "eligible_contacts": len(eligible),
        "blocked_contacts": len(contacts) - len(eligible),
        "simulation": simulation,
        "template": template,
        "integration": integration,
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
            key = hashlib.sha256(f"{campaign.id}:{contact.id}:{campaign.channel.value}".encode()).hexdigest()
            db.add(CampaignRecipient(campaign_id=campaign.id, contact_id=contact.id, idempotency_key=key))
    db.flush()
    return db.scalar(select(func.count(CampaignRecipient.id)).where(CampaignRecipient.campaign_id == campaign.id)) or 0


def campaign_message(campaign: Campaign) -> str:
    parts = [campaign.title.strip(), campaign.body.strip()]
    if campaign.call_to_action:
        parts.append(campaign.call_to_action.strip())
    return "\n\n".join(part for part in parts if part)


def whatsapp_components(campaign: Campaign, template: MessageTemplate | None) -> list[dict] | None:
    if not template:
        return None
    indexes = [int(value) for value in re.findall(r"\{\{\s*(\d+)\s*\}\}", template.body)]
    if not indexes:
        return None
    values = [campaign.body, campaign.title, campaign.call_to_action or "", campaign.link_url or ""]
    parameters = []
    for index in range(1, max(indexes) + 1):
        value = values[index - 1] if index <= len(values) else ""
        parameters.append({"type": "text", "text": value})
    return [{"type": "body", "parameters": parameters}]


async def execute_social_campaign(
    db: Session,
    campaign: Campaign,
    integration: CompanyIntegration,
) -> dict:
    existing = db.scalars(
        select(CampaignChannel)
        .where(CampaignChannel.campaign_id == campaign.id, CampaignChannel.channel == campaign.channel)
        .order_by(CampaignChannel.created_at.desc(), CampaignChannel.id.desc())
    ).first()
    if existing and existing.status in {"sending", "published", "simulated"}:
        if existing.status == "published":
            campaign.status = CampaignStatus.sent
        elif existing.status == "simulated":
            campaign.status = CampaignStatus.simulated
        else:
            campaign.status = CampaignStatus.failed
            existing.status = "failed"
        db.commit()
        return {"status": "ignored", "reason": "Esta publicação já foi processada ou ficou com resultado externo indeterminado."}
    channel_record = existing or CampaignChannel(campaign_id=campaign.id, channel=campaign.channel)
    channel_record.status = "sending"
    db.add(channel_record)
    db.commit()

    message = campaign_message(campaign)
    tracked_link = make_tracking_url(campaign.id) if campaign.link_url else None
    try:
        if campaign.channel == Channel.facebook:
            result = await facebook_service.publish(
                message,
                tracked_link,
                campaign.image_path,
                campaign.video_path,
                page_id=integration.external_account_id or "",
                access_token=integration.credentials.get("page_access_token", ""),
            )
        else:
            media_url = campaign.video_path or campaign.image_path
            if not media_url or not media_url.startswith("https://"):
                raise IntegrationError("Instagram requer uma URL pública HTTPS para a imagem ou vídeo.")
            caption = f"{message}\n\n{campaign.link_url}" if campaign.link_url else message
            result = await instagram_service.publish_media(
                media_url,
                caption,
                is_video=bool(campaign.video_path),
                account_id=integration.external_account_id or "",
                access_token=integration.credentials.get("page_access_token", ""),
            )
    except IntegrationError as exc:
        channel_record.status = "failed"
        campaign.status = CampaignStatus.failed
        db.commit()
        logger.warning("Falha externa campaign_id=%s channel=%s: %s", campaign.id, campaign.channel.value, exc)
        return {"status": "failed", "reason": str(exc)}

    channel_record.external_id = result.external_id
    if result.success:
        channel_record.status = "published"
        campaign.status = CampaignStatus.sent
        status = "sent"
    elif result.simulated:
        channel_record.status = "simulated"
        campaign.status = CampaignStatus.simulated
        status = "simulation"
    else:
        channel_record.status = "failed"
        campaign.status = CampaignStatus.failed
        status = "failed"
    db.commit()
    return {"status": status, "message": result.error, "external_id": result.external_id}


async def execute_campaign(db: Session, campaign_id: int) -> dict:
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if not campaign or campaign.status in {CampaignStatus.cancelled, CampaignStatus.sent, CampaignStatus.simulated}:
        return {"status": "ignored", "reason": "Campanha inexistente, cancelada ou já concluída."}
    allowed, reason = check_company_limits(db, campaign.company_id)
    if not allowed:
        campaign.status = CampaignStatus.failed
        db.commit()
        return {"status": "paused", "reason": reason}
    campaign.status = CampaignStatus.sending
    db.commit()

    if campaign.channel in {Channel.facebook, Channel.instagram}:
        integration = load_company_integration(db, campaign.company_id, campaign.channel.value)
        if not settings.simulation_mode and not integration.active:
            campaign.status = CampaignStatus.failed
            db.commit()
            return {"status": "failed", "reason": "Teste e ative a integração oficial antes de publicar."}
        return await execute_social_campaign(db, campaign, integration)

    recipient_count = materialize_recipients(db, campaign)
    if recipient_count > settings.large_campaign_threshold and not campaign.approved_at:
        campaign.status = CampaignStatus.review
        campaign.requires_confirmation = True
        db.commit()
        return {"status": "review", "reason": "Confirmação adicional obrigatória para campanha grande."}
    readiness = validate_whatsapp_readiness(
        db,
        campaign.company_id,
        campaign.contact_list_id,
        campaign.message_template_id,
    )
    if not readiness["ready"]:
        campaign.status = CampaignStatus.failed
        db.commit()
        return {"status": "failed", "reason": readiness["reason"]}

    template = readiness["template"]
    integration = readiness["integration"]
    recipients = db.scalars(
        select(CampaignRecipient)
        .where(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status.in_(["pending", "failed"]))
        .options(selectinload(CampaignRecipient.contact))
        .order_by(CampaignRecipient.id)
    ).all()
    sent = failed = simulated = blocked = 0
    for recipient in recipients:
        allowed, reason = check_company_limits(db, campaign.company_id)
        if not allowed:
            recipient.error_message = reason
            break
        if not has_valid_consent(db, recipient.contact, Channel.whatsapp):
            recipient.status, recipient.error_message = "blocked", "Contato sem consentimento válido."
            blocked += 1
            db.add(DeliveryEvent(campaign_id=campaign.id, recipient_id=recipient.id, external_id=None, event_type="blocked", payload={}))
            db.commit()
            continue

        # Conditional durable claim before external I/O. Even if two workers
        # loaded the same pending row, only one may transition it to sending.
        claimed = db.execute(
            update(CampaignRecipient)
            .where(
                CampaignRecipient.id == recipient.id,
                CampaignRecipient.status.in_(["pending", "failed"]),
            )
            .values(status="sending", error_message=None)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        if not claimed:
            continue
        db.refresh(recipient)
        try:
            result: SendResult = await whatsapp_service.send_template(
                recipient.contact.phone,
                template.name if template else "simulation_only",
                template.language if template else "pt_BR",
                phone_number_id=integration.external_account_id or "",
                access_token=integration.credentials.get("access_token", ""),
                components=whatsapp_components(campaign, template),
            )
            if result.success:
                recipient.status, recipient.external_message_id = "sent", result.external_id
                sent += 1
            elif result.simulated:
                recipient.status, recipient.error_message = "simulated", result.error
                simulated += 1
            else:
                recipient.status, recipient.error_message = "failed", result.error
                failed += 1
            db.add(
                DeliveryEvent(
                    campaign_id=campaign.id,
                    recipient_id=recipient.id,
                    external_id=result.external_id,
                    event_type=recipient.status,
                    payload={"simulated": result.simulated},
                )
            )
            db.commit()
            if result.success and settings.minute_message_limit > 0:
                await asyncio.sleep(60 / settings.minute_message_limit)
        except IntegrationError as exc:
            recipient.status, recipient.error_message = "failed", str(exc)
            failed += 1
            db.add(DeliveryEvent(campaign_id=campaign.id, recipient_id=recipient.id, external_id=None, event_type="failed", payload={}))
            db.commit()

    counts = dict(
        db.execute(
            select(CampaignRecipient.status, func.count(CampaignRecipient.id))
            .where(CampaignRecipient.campaign_id == campaign.id)
            .group_by(CampaignRecipient.status)
        ).all()
    )
    if counts.get("sending"):
        campaign.status = CampaignStatus.failed
    elif counts.get("pending") or counts.get("failed") or counts.get("blocked"):
        campaign.status = CampaignStatus.failed
    elif counts.get("sent") or counts.get("delivered") or counts.get("read"):
        campaign.status = CampaignStatus.sent
    elif counts.get("simulated"):
        campaign.status = CampaignStatus.simulated
    else:
        campaign.status = CampaignStatus.failed
    db.commit()
    return {
        "status": campaign.status.value,
        "sent": sent,
        "failed": failed,
        "blocked": blocked,
        "simulated": simulated,
        "remaining": counts.get("pending", 0),
    }
