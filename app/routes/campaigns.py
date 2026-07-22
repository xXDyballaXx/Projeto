from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Campaign, CampaignChannel, CampaignRecipient, CampaignStatus, Channel, ContactList, DeliveryEvent, ScheduledTask, User
from app.repositories.audit import audit
from app.schemas import CampaignCreate, CampaignOutput, CampaignUpdate
from app.security.auth import get_current_user
from app.tasks.campaign_tasks import send_campaign
from app.services.campaign_service import validate_whatsapp_readiness

router = APIRouter(prefix="/api/campaigns", tags=["Campanhas"])
logger = logging.getLogger("divulgai.campaigns")
ALLOWED_UPLOADS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4"}


def valid_file_signature(content_type: str, content: bytes) -> bool:
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        "video/mp4": len(content) > 12 and content[4:8] == b"ftyp",
    }
    return signatures.get(content_type, False)


def local_media_path(url: str | None, company_id: int) -> Path | None:
    if not url or f"/uploads/{company_id}/" not in url:
        return None
    upload_root = (Path("uploads") / str(company_id)).resolve()
    candidate = (upload_root / Path(url.split("?", 1)[0]).name).resolve()
    if candidate.parent != upload_root:
        logger.warning("Caminho de mídia recusado durante limpeza company_id=%s", company_id)
        return None
    return candidate


def remove_local_media(url: str | None, company_id: int) -> None:
    candidate = local_media_path(url, company_id)
    if candidate is None:
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        logger.exception("Não foi possível remover mídia local company_id=%s", company_id)


def scoped_campaign(db: Session, user: User, campaign_id: int) -> Campaign:
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id, Campaign.company_id == user.company_id))
    if not campaign:
        raise HTTPException(404, "Campanha não encontrada.")
    return campaign


def revoke_queued_task(task: ScheduledTask) -> None:
    if not task.celery_task_id or task.status not in {"pending", "queued"}:
        return
    try:
        send_campaign.app.control.revoke(task.celery_task_id)
    except Exception:
        logger.warning("Não foi possível revogar a tarefa Celery task_id=%s", task.id)


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
        readiness = validate_whatsapp_readiness(db, user.company_id, data.contact_list_id, data.message_template_id)
        if not readiness["ready"]:
            raise HTTPException(422, readiness["reason"])
    elif data.message_template_id:
        raise HTTPException(422, "Templates de mensagem são exclusivos de campanhas do WhatsApp.")
    values = data.model_dump(exclude={"confirm_large_campaign"})
    if values.get("link_url"):
        values["link_url"] = str(values["link_url"])
    if data.scheduled_at:
        values["status"] = CampaignStatus.scheduled
    campaign = Campaign(company_id=user.company_id, created_by_id=user.id, **values)
    if contact_list and len(contact_list.contacts) > settings.large_campaign_threshold:
        campaign.requires_confirmation = True
        if data.confirm_large_campaign:
            campaign.approved_at = datetime.now(timezone.utc)
        elif data.scheduled_at:
            raise HTTPException(409, "Confirme a revisão da base antes de agendar uma campanha grande.")
    db.add(campaign)
    db.flush()
    audit(db, "campaign.created", user, "campaign", campaign.id)
    if campaign.scheduled_at:
        _schedule(db, campaign, user)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignOutput)
def update_campaign(campaign_id: int, data: CampaignUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status in {CampaignStatus.sending, CampaignStatus.sent, CampaignStatus.simulated, CampaignStatus.failed}:
        raise HTTPException(409, "Campanhas processadas não podem ser editadas. Duplique a campanha para preservar o histórico.")
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
    final_template_id = changes.get("message_template_id", campaign.message_template_id)
    if final_channel.value == "whatsapp":
        readiness = validate_whatsapp_readiness(db, user.company_id, final_list_id, final_template_id)
        if not readiness["ready"]:
            raise HTTPException(422, readiness["reason"])
    else:
        changes["message_template_id"] = None
    tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign.id)).all()
    for task in tasks:
        revoke_queued_task(task)
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
    if campaign.scheduled_at:
        _schedule(db, campaign, user)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status in {CampaignStatus.sending, CampaignStatus.sent, CampaignStatus.simulated, CampaignStatus.failed}:
        raise HTTPException(409, "Campanhas processadas são mantidas para preservar o histórico e a auditoria.")
    tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign.id)).all()
    for task in tasks:
        revoke_queued_task(task)
        db.delete(task)
    db.execute(sa_delete(DeliveryEvent).where(DeliveryEvent.campaign_id == campaign.id))
    db.execute(sa_delete(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id))
    db.execute(sa_delete(CampaignChannel).where(CampaignChannel.campaign_id == campaign.id))
    media_urls = (campaign.image_path, campaign.video_path)
    audit(db, "campaign.deleted", user, "campaign", campaign.id, {"name": campaign.internal_name})
    db.delete(campaign)
    db.commit()
    for media_url in media_urls:
        remove_local_media(media_url, user.company_id)
    return Response(status_code=204)


def _schedule(db: Session, campaign: Campaign, user: User):
    execute_at = campaign.scheduled_at
    if execute_at and execute_at.tzinfo is None:
        execute_at = execute_at.replace(tzinfo=timezone.utc)
    if not execute_at or execute_at <= datetime.now(timezone.utc):
        raise HTTPException(400, "Escolha uma data futura para o agendamento.")
    task = ScheduledTask(company_id=user.company_id, campaign_id=campaign.id, execute_at=execute_at)
    db.add(task)
    db.flush()
    audit(db, "campaign.scheduled", user, "campaign", campaign.id, {"task_id": task.id, "execute_at": execute_at.isoformat()})
    return task


@router.post("/{campaign_id}/send")
def send_now(campaign_id: int, confirm: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status == CampaignStatus.cancelled:
        raise HTTPException(409, "Campanha cancelada não pode ser enviada.")
    if campaign.status in {CampaignStatus.sending, CampaignStatus.sent, CampaignStatus.simulated}:
        raise HTTPException(409, "Esta campanha já está em processamento ou foi concluída. Duplique-a para um novo envio.")
    if campaign.requires_confirmation and not confirm:
        raise HTTPException(409, "Confirmação adicional necessária para esta campanha.")
    previous_status = campaign.status
    if confirm:
        campaign.approved_at = datetime.now(timezone.utc)
    pending_tasks = db.scalars(
        select(ScheduledTask).where(
            ScheduledTask.campaign_id == campaign.id,
            ScheduledTask.status.in_(["pending", "queued"]),
        )
    ).all()
    for pending_task in pending_tasks:
        revoke_queued_task(pending_task)
        pending_task.status = "cancelled"
    task = ScheduledTask(company_id=user.company_id, campaign_id=campaign.id, execute_at=datetime.now(timezone.utc), status="queued")
    db.add(task)
    campaign.status = CampaignStatus.sending
    audit(db, "campaign.queued", user, "campaign", campaign.id)
    db.commit()
    try:
        result = send_campaign.delay(campaign.id, task.id)
    except Exception as exc:
        campaign.status = previous_status
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
    if campaign.status in {CampaignStatus.sent, CampaignStatus.sending, CampaignStatus.simulated, CampaignStatus.failed}:
        raise HTTPException(409, "Uma campanha em envio ou concluída não pode ser cancelada por esta ação.")
    campaign.status = CampaignStatus.cancelled
    tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.campaign_id == campaign.id, ScheduledTask.status.in_(["pending", "queued"]))).all()
    for task in tasks:
        revoke_queued_task(task)
        task.status = "cancelled"
    audit(db, "campaign.cancelled", user, "campaign", campaign.id, {"tasks": len(tasks)})
    db.commit()
    return {"message": "Agendamento cancelado."}


@router.post("/{campaign_id}/duplicate", response_model=CampaignOutput, status_code=201)
def duplicate(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    source = scoped_campaign(db, user, campaign_id)
    fields = ["title", "body", "call_to_action", "link_url", "image_path", "video_path", "channel", "contact_list_id", "message_template_id", "timezone"]
    campaign = Campaign(company_id=user.company_id, created_by_id=user.id, internal_name=f"Cópia de {source.internal_name}", **{field: getattr(source, field) for field in fields})
    db.add(campaign)
    db.flush()
    audit(db, "campaign.duplicated", user, "campaign", campaign.id, {"source_campaign_id": source.id})
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/upload")
async def upload_media(campaign_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status in {CampaignStatus.sending, CampaignStatus.sent, CampaignStatus.simulated, CampaignStatus.failed}:
        raise HTTPException(409, "A mídia de uma campanha em processamento ou concluída não pode ser alterada.")
    if file.content_type not in ALLOWED_UPLOADS:
        raise HTTPException(400, "Formato inválido. Use JPG, PNG, WebP ou MP4.")
    content = await file.read((settings.max_upload_mb * 1024 * 1024) + 1)
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Arquivo excede {settings.max_upload_mb} MB.")
    if not valid_file_signature(file.content_type, content):
        raise HTTPException(400, "O conteúdo do arquivo não corresponde ao formato informado.")
    upload_dir = Path("uploads") / str(user.company_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    old_media_urls = (campaign.image_path, campaign.video_path)
    current_usage = sum(item.stat().st_size for item in upload_dir.iterdir() if item.is_file())
    replaceable_files = {
        str(candidate): candidate
        for old_url in old_media_urls
        if (candidate := local_media_path(old_url, user.company_id)) is not None and candidate.is_file()
    }
    replaceable_usage = sum(candidate.stat().st_size for candidate in replaceable_files.values())
    company_quota = settings.max_company_upload_mb * 1024 * 1024
    if current_usage - replaceable_usage + len(content) > company_quota:
        raise HTTPException(413, f"A empresa atingiu a cota de {settings.max_company_upload_mb} MB para mídias.")
    filename = f"{uuid4().hex}{ALLOWED_UPLOADS[file.content_type]}"
    path = upload_dir / filename
    path.write_bytes(content)
    public_url = f"{settings.base_url.rstrip('/')}/uploads/{user.company_id}/{filename}"
    if file.content_type.startswith("image/"):
        campaign.image_path = public_url
        campaign.video_path = None
    else:
        campaign.video_path = public_url
        campaign.image_path = None
    audit(db, "campaign.media_uploaded", user, "campaign", campaign.id, {"content_type": file.content_type})
    try:
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    for old_url in old_media_urls:
        if old_url and old_url != public_url:
            remove_local_media(old_url, user.company_id)
    return {"message": "Arquivo validado e salvo.", "url": public_url}


@router.get("/history/all")
def history(
    q: str = Query("", max_length=160),
    channel: Channel | None = None,
    status: CampaignStatus | None = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    terminal_statuses = [
        CampaignStatus.sent,
        CampaignStatus.simulated,
        CampaignStatus.failed,
        CampaignStatus.cancelled,
    ]
    stmt = select(Campaign).where(
        Campaign.company_id == user.company_id,
        Campaign.status.in_(terminal_statuses),
    )
    if q:
        stmt = stmt.where(Campaign.internal_name.ilike(f"%{q}%"))
    if channel:
        stmt = stmt.where(Campaign.channel == channel)
    if status:
        if status not in terminal_statuses:
            raise HTTPException(422, "O histórico aceita apenas estados finalizados.")
        stmt = stmt.where(Campaign.status == status)
    campaigns = db.scalars(stmt.order_by(Campaign.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"id": c.id, "campaign": c.internal_name, "channel": c.channel, "date": c.scheduled_at or c.created_at, "status": c.status, "recipients": len(c.recipients), "sent": sum(r.status in {"sent", "delivered", "read"} for r in c.recipients), "failures": sum(r.status in {"failed", "blocked"} for r in c.recipients)} for c in campaigns]


@router.get("/history/{campaign_id}")
def history_detail(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = scoped_campaign(db, user, campaign_id)
    if campaign.status not in {
        CampaignStatus.sent,
        CampaignStatus.simulated,
        CampaignStatus.failed,
        CampaignStatus.cancelled,
    }:
        raise HTTPException(404, "A campanha ainda não possui histórico finalizado.")
    events = db.scalars(
        select(DeliveryEvent)
        .where(DeliveryEvent.campaign_id == campaign.id)
        .order_by(DeliveryEvent.occurred_at.desc())
        .limit(100)
    ).all()
    return {
        "id": campaign.id,
        "name": campaign.internal_name,
        "title": campaign.title,
        "body": campaign.body,
        "channel": campaign.channel,
        "status": campaign.status,
        "scheduled_at": campaign.scheduled_at,
        "created_at": campaign.created_at,
        "recipients": [
            {
                "id": recipient.id,
                "status": recipient.status,
                "external_message_id": recipient.external_message_id,
                "error": recipient.error_message,
            }
            for recipient in campaign.recipients
        ],
        "events": [
            {"type": event.event_type, "date": event.occurred_at, "external_id": event.external_id}
            for event in events
        ],
    }


@router.get("/tasks/all")
def tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(ScheduledTask).where(ScheduledTask.company_id == user.company_id).order_by(ScheduledTask.created_at.desc()).limit(200)).all()
    return [{"id": item.id, "campaign_id": item.campaign_id, "status": item.status, "attempts": item.attempts, "created_at": item.created_at, "execute_at": item.execute_at, "error": item.error_message, "result": item.result} for item in items]
