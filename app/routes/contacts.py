import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Consent, Contact, ContactList, User
from app.repositories.audit import audit
from app.schemas import ConsentInput, ContactCreate, ContactListCreate, ContactOutput, ContactUpdate
from app.security.auth import get_current_user
from app.services.consent_service import revoke_consent

router = APIRouter(prefix="/api/contacts", tags=["Contatos"])


def scoped_contact(db: Session, user: User, contact_id: int) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.id == contact_id, Contact.company_id == user.company_id).options(selectinload(Contact.consents)))
    if not contact:
        raise HTTPException(404, "Contato não encontrado.")
    return contact


@router.get("", response_model=list[ContactOutput])
def list_contacts(q: str = "", active: bool | None = None, limit: int = Query(100, le=500), offset: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(contact, key, value)
    audit(db, "contact.updated", user, "contact", contact.id)
    db.commit()
    return contact


@router.post("/{contact_id}/consents", response_model=ContactOutput)
def add_consent(contact_id: int, data: ConsentInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact = scoped_contact(db, user, contact_id)
    if data.is_granted:
        db.add(Consent(contact_id=contact.id, **data.model_dump()))
    else:
        revoke_consent(db, contact, data.channel, data.source, data.proof)
    audit(db, "consent.changed", user, "contact", contact.id, {"channel": data.channel.value, "granted": data.is_granted})
    db.commit()
    return scoped_contact(db, user, contact.id)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact = scoped_contact(db, user, contact_id)
    audit(db, "contact.deleted", user, "contact", contact.id)
    from app.models import CampaignRecipient
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
    created, skipped, errors = 0, 0, []
    for number, row in enumerate(reader, start=2):
        try:
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
                    db.add(Consent(contact_id=contact.id, channel=row.get("canal", "whatsapp"), is_granted=True, source=row.get("origem") or "csv", proof="Declaração no arquivo importado"))
                created += 1
        except Exception:
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
    for contact in contacts:
        writer.writerow([contact.name, contact.phone, contact.email or "", ",".join(contact.tags), contact.source, "sim" if contact.is_active else "não"])
    return Response(stream.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=contatos.csv"})


@router.post("/lists", status_code=201)
def create_list(data: ContactListCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contact_list = ContactList(company_id=user.company_id, name=data.name, description=data.description)
    if data.contact_ids:
        contact_list.contacts = db.scalars(select(Contact).where(Contact.company_id == user.company_id, Contact.id.in_(data.contact_ids))).all()
    db.add(contact_list)
    db.commit()
    db.refresh(contact_list)
    return {"id": contact_list.id, "name": contact_list.name, "contacts": len(contact_list.contacts)}


@router.get("/lists/all")
def list_lists(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lists = db.scalars(select(ContactList).where(ContactList.company_id == user.company_id).options(selectinload(ContactList.contacts))).all()
    return [{"id": item.id, "name": item.name, "description": item.description, "contacts": len(item.contacts)} for item in lists]
