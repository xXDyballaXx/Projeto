from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import GeneratedContent, User
from app.repositories.audit import audit
from app.schemas import ContentApprovalRequest, GenerateContentRequest
from app.security.auth import get_current_user
from app.services.ai_service import ai_service
from app.services.integration_credentials import load_company_integration

router = APIRouter(prefix="/api/content", tags=["Conteúdo com IA"])


@router.post("/generate")
async def generate(data: GenerateContentRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    generated_today = db.scalar(
        select(func.count(GeneratedContent.id)).where(
            GeneratedContent.company_id == user.company_id,
            GeneratedContent.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
        )
    ) or 0
    generated_recently = db.scalar(
        select(func.count(GeneratedContent.id)).where(
            GeneratedContent.company_id == user.company_id,
            GeneratedContent.created_at >= now - timedelta(minutes=1),
        )
    ) or 0
    if generated_today >= settings.daily_ai_generation_limit:
        raise HTTPException(429, "O limite diário de gerações de conteúdo foi atingido.")
    if generated_recently >= settings.minute_ai_generation_limit:
        raise HTTPException(429, "Aguarde um minuto antes de gerar mais conteúdo.")
    integration = load_company_integration(db, user.company_id, "ai")
    api_key = integration.credentials.get("api_key", "")
    if not settings.simulation_mode and not integration.active:
        raise HTTPException(503, "Teste e ative a integração de IA antes de gerar conteúdo real.")
    text, provider = await ai_service.generate(data, api_key=api_key)
    generated = GeneratedContent(company_id=user.company_id, user_id=user.id, prompt_data=data.model_dump(mode="json"), content=text, provider=provider)
    db.add(generated)
    db.flush()
    audit(
        db,
        "content.generated",
        user,
        "generated_content",
        generated.id,
        {"provider": provider, "channel": data.channel.value},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(generated)
    return {"id": generated.id, "content": text, "provider": provider, "requires_human_approval": True}


@router.post("/{content_id}/approve")
def approve(
    content_id: int,
    request: Request,
    data: ContentApprovalRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    generated = db.get(GeneratedContent, content_id)
    if not generated or generated.company_id != user.company_id:
        raise HTTPException(404, "Conteúdo não encontrado.")
    if data and data.content is not None:
        generated.content = data.content.strip()
    generated.status = "approved"
    audit(
        db,
        "content.approved",
        user,
        "generated_content",
        generated.id,
        {"edited": bool(data and data.content is not None)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {
        "message": "Conteúdo aprovado para ser usado manualmente em uma campanha.",
        "id": generated.id,
        "status": generated.status,
        "content": generated.content,
    }

