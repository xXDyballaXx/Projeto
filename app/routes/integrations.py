from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ApiCredential, Integration, MessageTemplate, User
from app.repositories.audit import audit
from app.schemas import IntegrationCreate
from app.security.auth import get_current_user
from app.security.crypto import encrypt_secret, mask_secret
from app.services.integration_credentials import load_company_integration

router = APIRouter(prefix="/api/integrations", tags=["Integrações"])
ALLOWED_CREDENTIALS = {
    "whatsapp": {"access_token"},
    "facebook": {"page_access_token"},
    "instagram": {"page_access_token"},
    "ai": {"api_key"},
}
ALLOWED_METADATA = {
    "whatsapp": {"business_account_id"},
    "facebook": set(),
    "instagram": set(),
    "ai": set(),
}


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
        output.append({"id": item.id, "provider": item.provider, "active": item.is_active, "account": item.external_account_id, "metadata": item.metadata_json, "credential_hints": hints, "last_tested_at": item.last_tested_at, "last_error": item.last_error})
    return output


@router.post("", status_code=201)
def save_integration(data: IntegrationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    unexpected = set(data.credentials) - ALLOWED_CREDENTIALS[data.provider]
    if unexpected:
        raise HTTPException(422, "A integração recebeu credenciais não reconhecidas.")
    unexpected_metadata = set(data.metadata) - ALLOWED_METADATA[data.provider]
    if unexpected_metadata:
        raise HTTPException(422, "A integração recebeu identificadores adicionais não reconhecidos.")
    if data.provider in {"whatsapp", "facebook", "instagram"} and not data.external_account_id:
        raise HTTPException(422, "Informe o identificador oficial da conta para esta integração.")
    integration = db.scalars(
        select(Integration)
        .where(Integration.company_id == user.company_id, Integration.provider == data.provider)
        .order_by(Integration.updated_at.desc(), Integration.id.desc())
    ).first()
    if not integration:
        integration = Integration(company_id=user.company_id, provider=data.provider)
        db.add(integration)
        db.flush()
    integration.external_account_id = data.external_account_id
    integration.metadata_json = {key: value.strip() for key, value in data.metadata.items() if value.strip()}
    integration.is_active = False
    integration.last_error = "Teste de conexão pendente."
    for key, value in data.credentials.items():
        if not value or len(value) > 5000:
            continue
        credential = db.scalars(
            select(ApiCredential)
            .where(ApiCredential.integration_id == integration.id, ApiCredential.key_name == key)
            .order_by(ApiCredential.updated_at.desc(), ApiCredential.id.desc())
        ).first()
        if not credential:
            credential = ApiCredential(integration_id=integration.id, key_name=key, encrypted_value="", masked_hint="")
            db.add(credential)
        credential.encrypted_value = encrypt_secret(value)
        credential.masked_hint = mask_secret(value)
    audit(db, "integration.saved", user, "integration", integration.id, {"provider": integration.provider})
    db.commit()
    return {
        "id": integration.id,
        "provider": integration.provider,
        "message": "Credenciais criptografadas e salvas. Execute o teste de conexão para ativar o canal.",
    }


@router.post("/{integration_id}/test")
async def test_integration(integration_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    integration = db.scalar(select(Integration).where(Integration.id == integration_id, Integration.company_id == user.company_id))
    if not integration:
        raise HTTPException(404, "Integração não encontrada.")
    resolved = load_company_integration(db, user.company_id, integration.provider)
    credentials = resolved.credentials
    integration.last_tested_at = datetime.now(timezone.utc)
    if not settings.external_services_enabled or settings.environment == "test":
        integration.is_active = False
        integration.last_error = "Chamadas externas estão desativadas neste ambiente."
        audit(db, "integration.test_blocked", user, "integration", integration.id, {"provider": integration.provider})
        db.commit()
        return {
            "connected": False,
            "simulation": True,
            "message": "Credenciais salvas, mas o teste real está bloqueado enquanto EXTERNAL_SERVICES_ENABLED=false.",
        }

    account_id = resolved.external_account_id
    token = credentials.get("api_key" if integration.provider == "ai" else "access_token" if integration.provider == "whatsapp" else "page_access_token")
    if not token or (integration.provider != "ai" and not account_id):
        integration.is_active = False
        integration.last_error = "Credenciais obrigatórias ausentes."
        db.commit()
        return {"connected": False, "simulation": False, "message": integration.last_error}

    if integration.provider == "ai":
        base = settings.ai_api_url.rsplit("/responses", 1)[0].rstrip("/")
        url = f"{base}/models/{settings.ai_model}"
        params = None
    else:
        url = f"https://graph.facebook.com/{settings.meta_graph_version}/{account_id}"
        fields = {
            "whatsapp": "id,display_phone_number,verified_name",
            "facebook": "id,name",
            "instagram": "id,username",
        }[integration.provider]
        params = {"fields": fields}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not payload.get("id"):
            raise ValueError("identificador ausente")
    except (httpx.HTTPError, ValueError):
        integration.is_active = False
        integration.last_error = "A API recusou as credenciais ou não confirmou as permissões necessárias."
        audit(db, "integration.test_failed", user, "integration", integration.id, {"provider": integration.provider})
        db.commit()
        return {"connected": False, "simulation": False, "message": integration.last_error}

    integration.is_active = True
    integration.last_error = None
    audit(db, "integration.test_succeeded", user, "integration", integration.id, {"provider": integration.provider})
    db.commit()
    warnings = []
    if integration.provider == "whatsapp" and (not settings.meta_app_secret or not settings.meta_verify_token):
        warnings.append("Configure META_APP_SECRET e META_VERIFY_TOKEN para validar webhooks de entrega e opt-out.")
    return {"connected": True, "simulation": False, "message": "Conexão confirmada pela API oficial.", "warnings": warnings}


@router.post("/{integration_id}/whatsapp/templates/sync")
async def sync_whatsapp_templates(
    integration_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integration = db.scalar(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.company_id == user.company_id,
            Integration.provider == "whatsapp",
        )
    )
    if not integration:
        raise HTTPException(404, "Integração do WhatsApp não encontrada.")
    if settings.simulation_mode:
        return {
            "synchronized": False,
            "simulation": True,
            "message": "A sincronização oficial fica disponível quando EXTERNAL_SERVICES_ENABLED=true.",
        }
    resolved = load_company_integration(db, user.company_id, "whatsapp")
    token = resolved.credentials.get("access_token")
    business_account_id = str(integration.metadata_json.get("business_account_id") or "").strip()
    if not integration.is_active or not token or not business_account_id:
        raise HTTPException(422, "Ative a integração e informe o ID da conta WhatsApp Business (WABA).")
    url = f"https://graph.facebook.com/{settings.meta_graph_version}/{business_account_id}/message_templates"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                url,
                params={"fields": "id,name,language,status,components", "limit": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ValueError("lista de templates ausente")
    except (httpx.HTTPError, TypeError, ValueError):
        integration.last_error = "A Meta não permitiu sincronizar os templates desta conta."
        audit(db, "integration.templates_sync_failed", user, "integration", integration.id, {"provider": "whatsapp"})
        db.commit()
        raise HTTPException(503, integration.last_error) from None

    synchronized = 0
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
            continue
        language = str(row.get("language") or "pt_BR")[:16]
        template = db.scalar(
            select(MessageTemplate).where(
                MessageTemplate.company_id == user.company_id,
                MessageTemplate.meta_template_id == str(row["id"]),
            )
        )
        if not template:
            template = MessageTemplate(
                company_id=user.company_id,
                name=str(row["name"])[:160],
                language=language,
                meta_template_id=str(row["id"])[:255],
                body="",
            )
            db.add(template)
        components = row.get("components") if isinstance(row.get("components"), list) else []
        body_component = next(
            (component for component in components if str(component.get("type", "")).upper() == "BODY"),
            {},
        )
        template.name = str(row["name"])[:160]
        template.language = language
        template.body = str(body_component.get("text") or template.body or "Template sem corpo retornado pela Meta")[:12000]
        official_status = str(row.get("status") or "pending").lower()
        template.status = official_status if official_status in {"approved", "pending", "rejected"} else "pending"
        synchronized += 1
    integration.last_error = None
    audit(db, "integration.templates_synchronized", user, "integration", integration.id, {"count": synchronized})
    db.commit()
    return {
        "synchronized": True,
        "simulation": False,
        "count": synchronized,
        "message": f"{synchronized} template(s) sincronizado(s) com a Meta.",
    }


@router.delete("/{integration_id}", status_code=204)
def delete_integration(integration_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    integration = db.scalar(select(Integration).where(Integration.id == integration_id, Integration.company_id == user.company_id))
    if not integration:
        raise HTTPException(404, "Integração não encontrada.")
    audit(db, "integration.deleted", user, "integration", integration.id, {"provider": integration.provider})
    db.execute(sa_delete(ApiCredential).where(ApiCredential.integration_id == integration.id))
    db.delete(integration)
    db.commit()
    return Response(status_code=204)


@router.get("/whatsapp/message-templates")
def list_whatsapp_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    templates = db.scalars(
        select(MessageTemplate)
        .where(MessageTemplate.company_id == user.company_id)
        .order_by(MessageTemplate.name, MessageTemplate.language)
    ).all()
    return [
        {
            "id": template.id,
            "name": template.name,
            "language": template.language,
            "status": template.status,
            "meta_template_id": template.meta_template_id,
        }
        for template in templates
    ]


@router.post("/whatsapp/message-templates", status_code=201)
def save_whatsapp_template(data: TemplateInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.status not in {"pending", "approved", "rejected"}:
        raise HTTPException(400, "Status de template inválido.")
    template = MessageTemplate(company_id=user.company_id, name=data.name, language=data.language, body=data.body, meta_template_id=data.meta_template_id, status="pending")
    db.add(template)
    db.commit()
    db.refresh(template)
    return {
        "id": template.id,
        "name": template.name,
        "status": template.status,
        "warning": "O template permanece pendente até que o status seja sincronizado e confirmado pela Meta.",
    }
