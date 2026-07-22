import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, engine
from app.models import Company, Contact


def test_sqlite_connections_enable_foreign_key_enforcement():
    with engine.connect() as connection:
        enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()

    assert enabled == 1


def test_sqlite_rejects_orphan_foreign_keys():
    with SessionLocal() as db:
        db.add(
            Contact(
                company_id=999_999,
                name="Contato orfao",
                phone="+5511999990000",
                tags=[],
                source="teste",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_sqlite_cascades_company_deletion_to_contacts():
    with SessionLocal() as db:
        company = Company(name="Empresa descartavel")
        db.add(company)
        db.flush()
        contact = Contact(
            company_id=company.id,
            name="Contato descartavel",
            phone="+5511999990001",
            tags=[],
            source="teste",
        )
        db.add(contact)
        db.commit()
        company_id, contact_id = company.id, contact.id

        db.execute(delete(Company).where(Company.id == company_id))
        db.commit()
        db.expunge_all()

        assert db.get(Contact, contact_id) is None
