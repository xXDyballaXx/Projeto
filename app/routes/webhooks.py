from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import CampaignRecipient, Channel, Contact, DeliveryEvent
from app.services.consent_service import revoke_consent
from app.services.whatsapp_service import whatsapp_service

router = APIRouter(prefix="/webhooks/meta", tags=["Webhooks Meta"])


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
    raw = await request.body()
    if not whatsapp_service.validate_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Assinatura inválida.")
    payload = await request.json()
    processed = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status in value.get("statuses", []):
                external_id, state = status.get("id"), status.get("status")
                recipient = db.scalar(select(CampaignRecipient).where(CampaignRecipient.external_message_id == external_id))
                if recipient and state in {"sent", "delivered", "read", "failed"}:
                    recipient.status = state
                    exists = db.scalar(select(DeliveryEvent.id).where(DeliveryEvent.external_id == external_id, DeliveryEvent.event_type == state))
                    if not exists:
                        db.add(DeliveryEvent(campaign_id=recipient.campaign_id, recipient_id=recipient.id, external_id=external_id, event_type=state, payload=status))
                        processed += 1
            for message in value.get("messages", []):
                text = message.get("text", {}).get("body", "").strip().casefold()
                if text in {"sair", "parar", "cancelar", "stop"}:
                    phone = "+" + "".join(filter(str.isdigit, message.get("from", "")))
                    contacts = db.scalars(select(Contact).where(Contact.phone == phone)).all()
                    for contact in contacts:
                        revoke_consent(db, contact, Channel.whatsapp, "webhook_whatsapp", "Solicitação recebida por mensagem")
                        processed += 1
    db.commit()
    return {"received": True, "processed": processed}
