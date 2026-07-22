from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import GeneratedContent, User
from app.schemas import GenerateContentRequest
from app.security.auth import get_current_user
from app.services.ai_service import ai_service

router = APIRouter(prefix="/api/content", tags=["Conteúdo com IA"])


@router.post("/generate")
async def generate(data: GenerateContentRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    text, provider = await ai_service.generate(data)
    generated = GeneratedContent(company_id=user.company_id, user_id=user.id, prompt_data=data.model_dump(mode="json"), content=text, provider=provider)
    db.add(generated)
    db.commit()
    db.refresh(generated)
    return {"id": generated.id, "content": text, "provider": provider, "requires_human_approval": True}


@router.post("/{content_id}/approve")
def approve(content_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    generated = db.get(GeneratedContent, content_id)
    if not generated or generated.company_id != user.company_id:
        from fastapi import HTTPException
        raise HTTPException(404, "Conteúdo não encontrado.")
    generated.status = "approved"
    db.commit()
    return {"message": "Conteúdo aprovado para ser usado manualmente em uma campanha."}

