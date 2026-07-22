from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Campaign, DeliveryEvent
from app.services.tracking_service import read_tracking_token

router = APIRouter(tags=["Rastreamento"])


@router.get("/track/{token}", include_in_schema=False)
def track_click(token: str, db: Session = Depends(get_db)):
    campaign_id = read_tracking_token(token)
    campaign = db.get(Campaign, campaign_id) if campaign_id else None
    if not campaign or not campaign.link_url:
        raise HTTPException(404, "Link inválido ou indisponível.")
    db.add(DeliveryEvent(campaign_id=campaign.id, external_id=f"click:{uuid4().hex}", event_type="clicked", payload={}))
    db.commit()
    return RedirectResponse(campaign.link_url, status_code=302)
