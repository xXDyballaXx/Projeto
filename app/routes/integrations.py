from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ApiCredential, Integration, MessageTemplate, User
from app.schemas import IntegrationCreate
from app.security.auth import get_current_user
from app.security.crypto import encrypt_secret, mask_secret

router = APIRouter(prefix="/api/integrations", tags=["Integrações"])


class TemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    language: str = "pt_BR"
    body: str = Field(min_length=1, max_length=4096)
    meta_template_id: str | None = None
    status: str = "pending"


@router.get("")
def list_integrations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    integrations = db.scalars(select(Integration).where(Integration.company_id == user.company_id)).all()
    output = []
    for item in integrations:
        hints = db.scalars(select(ApiCredential.masked_hint).where(ApiCredential.integration_id == item.id)).all()
        output.append({"id": item.id, "provider": item.provider, "active": item.is_active, "account": item.external_account_id, "credential_hints": hints, "last_tested_at": item.last_tested_at, "last_error": item.last_error})
    return output


@router.post("", status_code=201)
def save_integration(data: IntegrationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    integration = db.scalar(select(Integration).where(Integration.company_id == user.company_id, Integration.provider == data.provider))
    if not integration:
        integration = Integration(company_id=user.company_id, provider=data.provider)
        db.add(integration)
        db.flush()
    integration.external_account_id = data.external_account_id
    for key, value in data.credentials.items():
        if not value or len(value) > 5000:
            continue
        credential = db.scalar(select(ApiCredential).where(ApiCredential.integration_id == integration.id, ApiCredential.key_name == key))
        if not credential:
            credential = ApiCredential(integration_id=integration.id, key_name=key, encrypted_value="", masked_hint="")
            db.add(credential)
        credential.encrypted_value = encrypt_secret(value)
        credential.masked_hint = mask_secret(value)
    db.commit()
    return {"id": integration.id, "provider": integration.provider, "message": "Credenciais criptografadas e salvas. Reinicie o serviço após mapear os segredos ao ambiente."}


@router.post("/{integration_id}/test")
def test_integration(integration_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    integration = db.scalar(select(Integration).where(Integration.id == integration_id, Integration.company_id == user.company_id))
    if not integration:
        raise HTTPException(404, "Integração não encontrada.")
    configured = {
        "whatsapp": bool(settings.whatsapp_phone_number_id and settings.whatsapp_access_token),
        "facebook": bool(settings.facebook_page_id and settings.facebook_page_access_token),
        "instagram": bool(settings.instagram_account_id and settings.facebook_page_access_token),
        "ai": bool(settings.ai_api_key),
    }[integration.provider]
    integration.last_tested_at = datetime.now(timezone.utc)
    integration.is_active = configured
    integration.last_error = None if configured else "Credenciais não estão ativas no ambiente da aplicação."
    db.commit()
    return {"connected": configured, "simulation": not configured and settings.simulation_mode, "message": "Configuração detectada." if configured else "Integração desativada; o ambiente segue em modo simulado."}


@router.post("/whatsapp/message-templates", status_code=201)
def save_whatsapp_template(data: TemplateInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.status not in {"pending", "approved", "rejected"}:
        raise HTTPException(400, "Status de template inválido.")
    template = MessageTemplate(company_id=user.company_id, name=data.name, language=data.language, body=data.body, meta_template_id=data.meta_template_id, status=data.status)
    db.add(template)
    db.commit()
    db.refresh(template)
    return {"id": template.id, "name": template.name, "status": template.status, "warning": "O status deve refletir exatamente o retorno oficial da Meta."}
