import csv
import io
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Campaign, CampaignRecipient, Channel, Consent, Contact, ContactList, User
from app.repositories.audit import audit
from app.schemas import ConsentInput, ContactCreate, ContactListCreate, ContactListUpdate, ContactOutput, ContactUpdate
from app.security.auth import get_current_user
from app.services.consent_service import revoke_consent

router = APIRouter(prefix="/api/contacts", tags=["Contatos"])
logger = logging.getLogger("divulgai.contacts")


def scoped_contact(db: Session, user: User, contact_id: int) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.id == contact_id, Contact.company_id == user.company_id).options(selectinload(Contact.consents)))
    if not contact:
        raise HTTPException(404, "Contato não encontrado.")
    return contact


def scoped_list(db: Session, user: User, list_id: int) -> ContactList:
    contact_list = db.scalar(
        select(ContactList)
        .where(ContactList.id == list_id, ContactList.company_id == user.company_id)
        .options(selectinload(ContactList.contacts))
    )
    if not contact_list:
        raise HTTPException(404, "Lista de contatos não encontrada.")
    return contact_list


@router.get("", response_model=list[ContactOutput])
def list_contacts(q: str = "", active: bool | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Contact).where(Contact.company_id == user.company_id).options(selectinload(Contact.consents)).order_by(Contact.created_at.desc())
    if q:
        stmt = stmt.where(or_(Contact.name.ilike(f"%{q}%"), Contact.phone.ilike(f"%{q}%"), Contact.email.ilike(f"%{q}%")))
    if active is not None:
        stmt = stmt.where(Contact.is_active == active)
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@router.post("", response_model=ContactOutput, status_code=201)
def create_contact(data: ContactCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact = Contact(company_id=user.company_id, **data.model_dump(exclude={"consents"}))
    db.add(contact)
    try:
        db.flush()
        for consent in data.consents:
            db.add(Consent(contact_id=contact.id, **consent.model_dump()))
        audit(db, "contact.created", user, "contact", contact.id)
        db.commit()
        db.refresh(contact)
        return scoped_contact(db, user, contact.id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Telefone já cadastrado nesta empresa.") from exc


@router.patch("/{contact_id}", response_model=ContactOutput)
def update_contact(contact_id: int, data: ContactUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact = scoped_contact(db, user, contact_id)
    changes = data.model_dump(exclude_unset=True)
    if contact.permanently_blocked and (
        changes.get("permanently_blocked") is False or changes.get("is_active") is True
    ):
        raise HTTPException(409, "Um contato bloqueado permanentemente não pode ser reativado.")
    if changes.get("permanently_blocked") is True:
        changes["is_active"] = False
        for channel in Channel:
            revoke_consent(db, contact, channel, "bloqueio_manual", "Contato bloqueado permanentemente")
    for key, value in changes.items():
        setattr(contact, key, value)
    audit(db, "contact.updated", user, "contact", contact.id, {"fields": sorted(changes)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Telefone já cadastrado nesta empresa.") from exc
    return scoped_contact(db, user, contact.id)


@router.post("/{contact_id}/consents", response_model=ContactOutput)
def add_consent(contact_id: int, data: ConsentInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact = scoped_contact(db, user, contact_id)
    changed = False
    if data.is_granted:
        if contact.permanently_blocked:
            raise HTTPException(409, "Este contato está bloqueado permanentemente.")
        active = db.scalar(
            select(Consent)
            .where(
                Consent.contact_id == contact.id,
                Consent.channel == data.channel,
                Consent.is_granted.is_(True),
                Consent.revoked_at.is_(None),
            )
            .order_by(Consent.created_at.desc())
        )
        if not active:
            db.add(Consent(contact_id=contact.id, **data.model_dump()))
            changed = True
    else:
        changed = revoke_consent(db, contact, data.channel, data.source, data.proof)
    audit(db, "consent.changed", user, "contact", contact.id, {"channel": data.channel.value, "granted": data.is_granted, "changed": changed})
    db.commit()
    db.expire(contact, ["consents"])
    return scoped_contact(db, user, contact.id)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact = scoped_contact(db, user, contact_id)
    audit(db, "contact.deleted", user, "contact", contact.id)
    used_in_history = db.scalar(select(func.count(CampaignRecipient.id)).where(CampaignRecipient.contact_id == contact.id)) or 0
    if used_in_history:
        for consent in list(contact.consents):
            db.delete(consent)
        contact.name = "Titular excluído"
        contact.phone = f"+000{contact.company_id}{contact.id}"
        contact.email = None
        contact.tags = []
        contact.source = "dados_anonimizados"
        contact.is_active = False
        contact.permanently_blocked = True
    else:
        db.delete(contact)
    db.commit()
    return Response(status_code=204)


@router.get("/{contact_id}/export")
def export_contact_data(contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact = scoped_contact(db, user, contact_id)
    data = ContactOutput.model_validate(contact).model_dump(mode="json")
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": f"attachment; filename=contato-{contact.id}.json"})


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Envie um arquivo CSV.")
    content = await file.read(2_000_001)
    if len(content) > 2_000_000:
        raise HTTPException(413, "CSV excede 2 MB.")
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "Use CSV codificado em UTF-8.") from exc
    required_headers = {"nome", "telefone", "email", "consentimento", "canal", "origem"}
    headers = {str(item).strip().lower() for item in (reader.fieldnames or []) if item}
    if not text.strip() or not required_headers.issubset(headers):
        raise HTTPException(
            400,
            "O CSV deve conter os cabeçalhos: nome, telefone, email, consentimento, canal e origem.",
        )
    rows = [
        {str(key).strip().lower(): value for key, value in row.items() if key is not None}
        for row in reader
    ]
    if not rows:
        raise HTTPException(400, "O arquivo CSV não possui contatos para importar.")
    created, skipped, errors = 0, 0, []
    for number, row in enumerate(rows, start=2):
        try:
            was_created = False
            with db.begin_nested():
                consented = str(row.get("consentimento", "")).strip().lower() in {"sim", "true", "1", "yes"}
                data = ContactCreate(name=row.get("nome", ""), phone=row.get("telefone", ""), email=row.get("email") or None, source=row.get("origem") or "csv")
                if db.scalar(select(Contact).where(Contact.company_id == user.company_id, Contact.phone == data.phone)):
                    skipped += 1
                    continue
                contact = Contact(company_id=user.company_id, **data.model_dump(exclude={"consents"}))
                db.add(contact)
                db.flush()
                if consented:
                    consent = ConsentInput(
                        channel=(row.get("canal") or "whatsapp").strip().lower(),
                        is_granted=True,
                        source=row.get("origem") or "csv",
                        proof="Declaração no arquivo importado",
                    )
                    db.add(Consent(contact_id=contact.id, **consent.model_dump()))
                    db.flush()
                was_created = True
            if was_created:
                created += 1
        except (IntegrityError, StatementError, ValidationError, ValueError):
            errors.append(number)
        except Exception:
            logger.exception("Falha inesperada ao importar linha CSV %s", number)
            errors.append(number)
    audit(db, "contacts.imported", user, details={"created": created, "skipped": skipped, "error_rows": errors})
    db.commit()
    return {"created": created, "skipped": skipped, "error_rows": errors}


@router.get("/export/csv/all")
def export_csv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contacts = db.scalars(select(Contact).where(Contact.company_id == user.company_id)).all()
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["nome", "telefone", "email", "etiquetas", "origem", "ativo"])

    def safe_cell(value) -> str:
        text = str(value or "")
        return f"'{text}" if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text

    for contact in contacts:
        writer.writerow([
            safe_cell(contact.name),
            safe_cell(contact.phone),
            safe_cell(contact.email),
            safe_cell(",".join(contact.tags)),
            safe_cell(contact.source),
            "sim" if contact.is_active else "não",
        ])
    return Response("\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=contatos.csv"})


@router.post("/lists", status_code=201)
def create_list(data: ContactListCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = ContactList(company_id=user.company_id, name=data.name, description=data.description)
    if data.contact_ids:
        contacts = db.scalars(select(Contact).where(Contact.company_id == user.company_id, Contact.id.in_(data.contact_ids))).all()
        if len(contacts) != len(data.contact_ids):
            raise HTTPException(404, "Um ou mais contatos não pertencem a esta empresa.")
        contact_list.contacts = contacts
    db.add(contact_list)
    db.flush()
    audit(db, "contact_list.created", user, "contact_list", contact_list.id, {"contacts": len(contact_list.contacts)})
    db.commit()
    db.refresh(contact_list)
    return {"id": contact_list.id, "name": contact_list.name, "contacts": len(contact_list.contacts)}


@router.get("/lists/all")
def list_lists(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lists = db.scalars(select(ContactList).where(ContactList.company_id == user.company_id).options(selectinload(ContactList.contacts))).all()
    return [{"id": item.id, "name": item.name, "description": item.description, "contacts": len(item.contacts)} for item in lists]


@router.get("/lists/{list_id}")
def get_list(list_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = scoped_list(db, user, list_id)
    return {
        "id": contact_list.id,
        "name": contact_list.name,
        "description": contact_list.description,
        "contacts": len(contact_list.contacts),
        "contact_ids": [contact.id for contact in contact_list.contacts],
    }


@router.patch("/lists/{list_id}")
def update_list(list_id: int, data: ContactListUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = scoped_list(db, user, list_id)
    changes = data.model_dump(exclude_unset=True)
    if "contact_ids" in changes:
        contact_ids = changes.pop("contact_ids") or []
        contacts = db.scalars(select(Contact).where(Contact.company_id == user.company_id, Contact.id.in_(contact_ids))).all() if contact_ids else []
        if len(contacts) != len(contact_ids):
            raise HTTPException(404, "Um ou mais contatos não pertencem a esta empresa.")
        contact_list.contacts = contacts
    for key, value in changes.items():
        setattr(contact_list, key, value)
    audit(db, "contact_list.updated", user, "contact_list", contact_list.id, {"fields": sorted(data.model_fields_set)})
    db.commit()
    return {"id": contact_list.id, "name": contact_list.name, "description": contact_list.description, "contacts": len(contact_list.contacts), "contact_ids": [contact.id for contact in contact_list.contacts]}


@router.post("/lists/{list_id}/contacts/{contact_id}")
def add_contact_to_list(list_id: int, contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = scoped_list(db, user, list_id)
    contact = scoped_contact(db, user, contact_id)
    if contact not in contact_list.contacts:
        contact_list.contacts.append(contact)
        audit(db, "contact_list.member_added", user, "contact_list", contact_list.id, {"contact_id": contact.id})
        db.commit()
    return {"message": "Contato incluído na lista.", "contacts": len(contact_list.contacts)}


@router.delete("/lists/{list_id}/contacts/{contact_id}")
def remove_contact_from_list(list_id: int, contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = scoped_list(db, user, list_id)
    contact = scoped_contact(db, user, contact_id)
    if contact in contact_list.contacts:
        contact_list.contacts.remove(contact)
        audit(db, "contact_list.member_removed", user, "contact_list", contact_list.id, {"contact_id": contact.id})
        db.commit()
    return {"message": "Contato removido da lista.", "contacts": len(contact_list.contacts)}


@router.delete("/lists/{list_id}", status_code=204)
def delete_list(list_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = scoped_list(db, user, list_id)
    campaigns = db.scalar(select(func.count(Campaign.id)).where(Campaign.contact_list_id == contact_list.id)) or 0
    if campaigns:
        raise HTTPException(409, "Esta lista está vinculada a campanhas e não pode ser excluída.")
    audit(db, "contact_list.deleted", user, "contact_list", contact_list.id, {"name": contact_list.name})
    contact_list.contacts = []
    db.delete(contact_list)
    db.commit()
    return Response(status_code=204)
