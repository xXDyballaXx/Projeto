import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Campaign, DeliveryEvent
from app.services.tracking_service import read_tracking_token

router = APIRouter(tags=["Rastreamento"])


@router.get("/track/{token}", include_in_schema=False)
def track_click(token: str, request: Request, db: Session = Depends(get_db)):
    campaign_id = read_tracking_token(token)
    campaign = db.get(Campaign, campaign_id) if campaign_id else None
    if not campaign or not campaign.link_url:
        raise HTTPException(404, "Link inválido ou indisponível.")
    remote = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")[:300]
    day = datetime.now(timezone.utc).date().isoformat()
    fingerprint = hashlib.sha256(
        f"{settings.secret_key}:{campaign.id}:{day}:{remote}:{user_agent}".encode()
    ).hexdigest()
    external_id = f"click:{campaign.id}:{fingerprint}"
    exists = db.scalar(
        select(DeliveryEvent.id).where(
            DeliveryEvent.external_id == external_id,
            DeliveryEvent.event_type == "clicked",
        )
    )
    if not exists:
        db.add(DeliveryEvent(campaign_id=campaign.id, external_id=external_id, event_type="clicked", payload={"unique_day": day}))
        try:
            db.commit()
        except IntegrityError:
            # Outro request idêntico pode ter gravado o clique entre a consulta
            # e o commit. A unicidade do banco vence a corrida sem quebrar o link.
            db.rollback()
    return RedirectResponse(campaign.link_url, status_code=302)
