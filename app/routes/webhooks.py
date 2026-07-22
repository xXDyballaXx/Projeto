import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Campaign, CampaignRecipient, Channel, Contact, DeliveryEvent, Integration
from app.services.consent_service import revoke_consent
from app.services.whatsapp_service import whatsapp_service

router = APIRouter(prefix="/webhooks/meta", tags=["Webhooks Meta"])
logger = logging.getLogger("divulgai.webhooks")
STATUS_ORDER = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}


def add_delivery_event_once(
    db: Session,
    recipient: CampaignRecipient,
    external_id: str,
    state: str,
    payload: dict,
) -> bool:
    exists = db.scalar(
        select(DeliveryEvent.id).where(
            DeliveryEvent.external_id == external_id,
            DeliveryEvent.event_type == state,
        )
    )
    if exists:
        return False
    try:
        with db.begin_nested():
            db.add(
                DeliveryEvent(
                    campaign_id=recipient.campaign_id,
                    recipient_id=recipient.id,
                    external_id=external_id,
                    event_type=state,
                    payload=payload,
                )
            )
            db.flush()
    except IntegrityError:
        # Uma entrega concorrente do mesmo evento vence pela restrição
        # única sem invalidar as demais atualizações deste webhook.
        return False
    return True


def resolve_webhook_company(db: Session, value: dict) -> int | None:
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        return None
    phone_number_id = str(metadata.get("phone_number_id") or "").strip()
    if not phone_number_id:
        return None
    company_ids = set(
        db.scalars(
            select(Integration.company_id).where(
                Integration.provider == "whatsapp",
                Integration.external_account_id == phone_number_id,
                Integration.is_active.is_(True),
            )
        ).all()
    )
    return next(iter(company_ids)) if len(company_ids) == 1 else None


@router.get("")
def verify_webhook(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    if mode == "subscribe" and settings.meta_verify_token and token == settings.meta_verify_token:
        return Response(content=challenge or "", media_type="text/plain")
    raise HTTPException(403, "Falha na verificação do webhook.")


@router.post("")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > 2_000_000:
        raise HTTPException(413, "O webhook excede o limite permitido.")
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "O webhook excede o limite permitido.")
    if not whatsapp_service.validate_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Assinatura inválida.")
    try:
        payload = await request.json()
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "O webhook enviou um JSON inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "O webhook enviou um payload inválido.")
    processed = 0
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        raise HTTPException(400, "O webhook enviou uma lista de eventos inválida.")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue
            company_id = resolve_webhook_company(db, value)
            statuses = value.get("statuses", [])
            if not isinstance(statuses, list):
                statuses = []
            for status in statuses:
                if not isinstance(status, dict):
                    continue
                external_id = str(status.get("id") or "").strip()[:255]
                state = str(status.get("status") or "").strip().lower()
                if not external_id:
                    continue
                recipient_stmt = (
                    select(CampaignRecipient)
                    .join(Campaign, Campaign.id == CampaignRecipient.campaign_id)
                    .where(CampaignRecipient.external_message_id == external_id)
                )
                if company_id is not None:
                    recipient_stmt = recipient_stmt.where(Campaign.company_id == company_id)
                elif settings.environment != "test":
                    logger.warning("Status ignorado: phone_number_id sem tenant reconhecido")
                    continue
                recipient = db.scalar(recipient_stmt)
                if recipient and state in {"sent", "delivered", "read", "failed"}:
                    if state == "failed" and recipient.status not in {"delivered", "read"}:
                        recipient.status = state
                    elif state != "failed":
                        current_rank = STATUS_ORDER.get(recipient.status, 0) if recipient.status != "failed" else 0
                        if STATUS_ORDER[state] >= current_rank:
                            recipient.status = state
                    if add_delivery_event_once(db, recipient, external_id, state, status):
                        processed += 1
            messages = value.get("messages", [])
            if not isinstance(messages, list):
                messages = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                text_payload = message.get("text")
                text = str(text_payload.get("body") or "").strip().casefold() if isinstance(text_payload, dict) else ""
                if text in {"sair", "parar", "cancelar", "stop"}:
                    phone = "+" + "".join(filter(str.isdigit, str(message.get("from") or "")))
                    statement = select(Contact).where(Contact.phone == phone)
                    if company_id is not None:
                        statement = statement.where(Contact.company_id == company_id)
                    elif settings.environment != "test":
                        logger.warning("Opt-out ignorado: phone_number_id sem tenant reconhecido")
                        continue
                    contacts = db.scalars(statement).all()
                    if company_id is None and len({contact.company_id for contact in contacts}) != 1:
                        logger.warning("Opt-out de teste ignorado por ambiguidade entre empresas")
                        continue
                    for contact in contacts:
                        if revoke_consent(db, contact, Channel.whatsapp, "webhook_whatsapp", "Solicitação recebida por mensagem"):
                            processed += 1
    db.commit()
    logger.info("Webhook Meta processado events=%s", processed)
    return {"received": True, "processed": processed}
