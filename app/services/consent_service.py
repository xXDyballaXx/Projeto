from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, Consent, Contact, UnsubscribeRequest


def has_valid_consent(db: Session, contact: Contact, channel: Channel) -> bool:
    if not contact.is_active or contact.permanently_blocked:
        return False
    consent = db.scalar(
        select(Consent)
        .where(Consent.contact_id == contact.id, Consent.channel == channel)
        .order_by(Consent.created_at.desc())
    )
    return bool(consent and consent.is_granted and consent.revoked_at is None)


def revoke_consent(db: Session, contact: Contact, channel: Channel, source: str, reason: str | None = None) -> bool:
    now = datetime.now(timezone.utc)
    consents = db.scalars(
        select(Consent).where(Consent.contact_id == contact.id, Consent.channel == channel, Consent.is_granted.is_(True))
    ).all()
    for consent in consents:
        consent.is_granted = False
        consent.revoked_at = now
    if not consents:
        return False
    db.add(UnsubscribeRequest(contact_id=contact.id, channel=channel, source=source, reason=reason))
    return True

