from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Campaign, CampaignChannel, CampaignRecipient, CampaignStatus, ContactList, DeliveryEvent, ScheduledTask, User
from app.repositories.audit import audit
from app.schemas import CampaignCreate, CampaignOutput, CampaignUpdate
from app.security.auth import get_current_user
from app.tasks.campaign_tasks import send_campaign
from app.services.campaign_service import validate_whatsapp_readiness

router = APIRouter(prefix="/api/campaigns", tags=["Campanhas"])
ALLOWED_UPLOADS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4"}


def valid_file_signature(content_type: str, content: bytes) -> bool:
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        "video/mp4": len(content) > 12 and content[4:8] == b"ftyp",
    }
    return signatures.get(content_type, False)


def scoped_campaign(db: Session, user: User, campaign_id: int) -> Campaign:
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id, Campaign.company_id == user.company_id))
    if not campaign:
        raise HTTPException(404, "Campanha não encontrada.")
    return campaign


@router.get("", response_model=list[CampaignOutput])
def list_campaigns(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Campaign).where(Campaign.company_id == user.company_id).order_by(Campaign.created_at.desc())).all()


@router.post("", response_model=CampaignOutput, status_code=201)
def create_campaign(data: CampaignCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = None
    if data.contact_list_id:
        contact_list = db.scalar(select(ContactList).where(ContactList.id == data.contact_list_id, ContactList.company_id == user.company_id))
        if not contact_list:
            raise HTTPException(404, "Lista de contatos não encontrada.")
    if data.channel.value == "whatsapp":
        readiness = validate_whatsapp_readiness(db, user.company_id, data.contact_list_id)
        if not readiness["ready"]:
            raise HTTPException(422, readiness["reason"])
    values = data.model_dump(exclude={"confirm_large_campaign"})
    if values.get("link_url"):
        values["link_url"] = str(values["link_url"])
    if data.scheduled_at:
        values["status"] = CampaignStatus.scheduled
    campaign = Campaign(company_id=user.company_id, created_by_id=user.id, **values)
    if contact_list and len(contact_list.contacts) > settings.large_campaign_threshold:
        campaign.requires_confirmation = True
    db.add(campaign)
    db.flush()
    audit(db, "campaign.created", user, "campaign", campaign.id)
    db.commit()
    db.refresh(campaign)
    if campaign.scheduled_at:
        _schedule(db, campaign, user)
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignOutput)
def update_campaign(campaign_id: int, data: CampaignUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status in {CampaignStatus.sending, CampaignStatus.sent}:
        raise HTTPException(409, "Campanhas em envio ou já enviadas não podem ser editadas. Duplique a campanha para criar uma nova versão.")
    changes = data.model_dump(exclude_unset=True)
    contact_list = None
    if "contact_list_id" in changes and changes["contact_list_id"] is not None:
        contact_list = db.scalar(select(ContactList).where(ContactList.id == changes["contact_list_id"], ContactList.company_id == user.company_id))
        if not contact_list:
            raise HTTPException(404, "Lista de contatos não encontrada.")
    scheduled_at = changes.get("scheduled_at")
    if scheduled_at:
        comparable = scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc)
        if comparable <= datetime.now(timezone.utc):
            raise HTTPException(400, "Escolha uma data futura para o agendamento.")
    final_channel = changes.get("channel", campaign.channel)
    final_list_id = changes.get("contact_list_id", campaign.contact_list_id)
    if final_channel.value == "whatsapp":
        readiness = validate_whatsapp_readiness(db, user.company_id, final_list_id)
        if not readiness["ready"]:
            raise HTTPException(422, readiness["reason"])
    tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign.id)).all()
    for task in tasks:
        if task.celery_task_id and task.status in {"pending", "queued"}:
            send_campaign.app.control.revoke(task.celery_task_id)
        db.delete(task)
    db.execute(sa_delete(DeliveryEvent).where(DeliveryEvent.campaign_id == campaign.id))
    db.execute(sa_delete(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id))
    db.execute(sa_delete(CampaignChannel).where(CampaignChannel.campaign_id == campaign.id))
    if changes.get("link_url"):
        changes["link_url"] = str(changes["link_url"])
    for key, value in changes.items():
        setattr(campaign, key, value)
    if campaign.contact_list_id and contact_list is None:
        contact_list = db.scalar(select(ContactList).where(ContactList.id == campaign.contact_list_id, ContactList.company_id == user.company_id))
    campaign.approved_at = None
    campaign.requires_confirmation = bool(contact_list and len(contact_list.contacts) > settings.large_campaign_threshold)
    campaign.status = CampaignStatus.scheduled if campaign.scheduled_at else CampaignStatus.draft
    audit(db, "campaign.updated", user, "campaign", campaign.id)
    db.commit()
    db.refresh(campaign)
    if campaign.scheduled_at:
        _schedule(db, campaign, user)
    return campaign


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status == CampaignStatus.sending:
        raise HTTPException(409, "Aguarde o término do processamento antes de apagar a campanha.")
    tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign.id)).all()
    for task in tasks:
        if task.celery_task_id and task.status in {"pending", "queued"}:
            send_campaign.app.control.revoke(task.celery_task_id)
        db.delete(task)
    db.execute(sa_delete(DeliveryEvent).where(DeliveryEvent.campaign_id == campaign.id))
    db.execute(sa_delete(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id))
    db.execute(sa_delete(CampaignChannel).where(CampaignChannel.campaign_id == campaign.id))
    audit(db, "campaign.deleted", user, "campaign", campaign.id, {"name": campaign.internal_name})
    db.delete(campaign)
    db.commit()
    return Response(status_code=204)


def _schedule(db: Session, campaign: Campaign, user: User):
    execute_at = campaign.scheduled_at
    if execute_at and execute_at.tzinfo is None:
        execute_at = execute_at.replace(tzinfo=timezone.utc)
    if not execute_at or execute_at <= datetime.now(timezone.utc):
        raise HTTPException(400, "Escolha uma data futura para o agendamento.")
    task = ScheduledTask(company_id=user.company_id, campaign_id=campaign.id, execute_at=execute_at)
    db.add(task)
    db.commit()


@router.post("/{campaign_id}/send")
def send_now(campaign_id: int, confirm: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status == CampaignStatus.cancelled:
        raise HTTPException(409, "Campanha cancelada não pode ser enviada.")
    if campaign.requires_confirmation and not confirm:
        raise HTTPException(409, "Confirmação adicional necessária para esta campanha.")
    if confirm:
        campaign.approved_at = datetime.now(timezone.utc)
    task = ScheduledTask(company_id=user.company_id, campaign_id=campaign.id, execute_at=datetime.now(timezone.utc), status="queued")
    db.add(task)
    campaign.status = CampaignStatus.sending
    audit(db, "campaign.queued", user, "campaign", campaign.id)
    db.commit()
    try:
        result = send_campaign.delay(campaign.id)
    except Exception as exc:
        campaign.status = CampaignStatus.draft
        task.status = "failed"
        task.error_message = str(exc)[:1000]
        db.commit()
        raise HTTPException(503, "Fila indisponível. Verifique Redis e Celery antes de tentar novamente.") from exc
    task.celery_task_id = result.id
    db.commit()
    if settings.celery_task_always_eager:
        return {"message": "Campanha processada no modo local.", "task_id": result.id, "result": result.result}
    return {"message": "Campanha adicionada à fila.", "task_id": result.id}


@router.post("/{campaign_id}/cancel")
def cancel(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status in {CampaignStatus.sent, CampaignStatus.sending}:
        raise HTTPException(409, "Uma campanha em envio ou concluída não pode ser cancelada por esta ação.")
    campaign.status = CampaignStatus.cancelled
    tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign.id, ScheduledTask.status.in_(["pending", "queued"]))).all()
    for task in tasks:
        if task.celery_task_id:
            send_campaign.app.control.revoke(task.celery_task_id)
        task.status = "cancelled"
    db.commit()
    return {"message": "Agendamento cancelado."}


@router.post("/{campaign_id}/duplicate", response_model=CampaignOutput, status_code=201)
def duplicate(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    source = scoped_campaign(db, user, campaign_id)
    fields = ["title", "body", "call_to_action", "link_url", "image_path", "video_path", "channel", "contact_list_id", "timezone"]
    campaign = Campaign(company_id=user.company_id, created_by_id=user.id, internal_name=f"Cópia de {source.internal_name}", **{field: getattr(source, field) for field in fields})
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/upload")
async def upload_media(campaign_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if file.content_type not in ALLOWED_UPLOADS:
        raise HTTPException(400, "Formato inválido. Use JPG, PNG, WebP ou MP4.")
    content = await file.read((settings.max_upload_mb * 1024 * 1024) + 1)
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Arquivo excede {settings.max_upload_mb} MB.")
    if not valid_file_signature(file.content_type, content):
        raise HTTPException(400, "O conteúdo do arquivo não corresponde ao formato informado.")
    upload_dir = Path("uploads") / str(user.company_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{ALLOWED_UPLOADS[file.content_type]}"
    path = upload_dir / filename
    path.write_bytes(content)
    public_url = f"{settings.base_url.rstrip('/')}/uploads/{user.company_id}/{filename}"
    if file.content_type.startswith("image/"):
        campaign.image_path = public_url
    else:
        campaign.video_path = public_url
    db.commit()
    return {"message": "Arquivo validado e salvo.", "url": public_url}


@router.get("/history/all")
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaigns = db.scalars(select(Campaign).where(Campaign.company_id == user.company_id).order_by(Campaign.created_at.desc())).all()
    return [{"id": c.id, "campaign": c.internal_name, "channel": c.channel, "date": c.scheduled_at or c.created_at, "status": c.status, "recipients": len(c.recipients), "sent": sum(r.status in {"sent", "delivered", "read"} for r in c.recipients), "failures": sum(r.status in {"failed", "blocked"} for r in c.recipients)} for c in campaigns]


@router.get("/tasks/all")
def tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(ScheduledTask).where(ScheduledTask.company_id == user.company_id).order_by(ScheduledTask.created_at.desc()).limit(200)).all()
    return [{"id": item.id, "campaign_id": item.campaign_id, "status": item.status, "attempts": item.attempts, "created_at": item.created_at, "execute_at": item.execute_at, "error": item.error_message, "result": item.result} for item in items]
