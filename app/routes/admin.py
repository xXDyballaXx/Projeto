from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, Campaign, Company, Contact, Integration, User
from app.repositories.audit import audit
from app.security.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["Administração"])


class AdminUserUpdate(BaseModel):
    is_active: bool


class AdminCompanyLimitsUpdate(BaseModel):
    daily_limit: int = Field(ge=1, le=100000)


@router.get("/overview")
def overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "current_admin_id": admin.id,
        "users": db.scalar(select(func.count(User.id))) or 0,
        "companies": db.scalar(select(func.count(Company.id))) or 0,
        "campaigns": db.scalar(select(func.count(Campaign.id))) or 0,
        "blocked_contacts": db.scalar(select(func.count(Contact.id)).where(Contact.permanently_blocked.is_(True))) or 0,
        "integrations": db.scalar(select(func.count(Integration.id))) or 0,
        "recent_logs": [{"action": row.action, "date": row.created_at, "company_id": row.company_id} for row in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(50)).all()],
    }


@router.get("/users")
def list_users(
    q: str = Query("", max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))
    users = db.scalars(stmt.limit(limit).offset(offset)).all()
    company_names = {
        company.id: company.name
        for company in db.scalars(select(Company).where(Company.id.in_({item.company_id for item in users}))).all()
    }
    return [
        {
            "id": item.id,
            "name": item.name,
            "email": item.email,
            "company_id": item.company_id,
            "company": company_names.get(item.company_id),
            "role": item.role,
            "active": item.is_active,
            "created_at": item.created_at,
        }
        for item in users
    ]


@router.patch("/users/{user_id}")
def update_user_status(
    user_id: int,
    data: AdminUserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Usuário não encontrado.")
    if target.id == admin.id and not data.is_active:
        raise HTTPException(409, "Você não pode bloquear a própria conta administrativa.")
    if target.is_active != data.is_active:
        target.is_active = data.is_active
        target.token_version += 1
        audit(
            db,
            "admin.user_unblocked" if data.is_active else "admin.user_blocked",
            admin,
            "user",
            target.id,
            {"company_id": target.company_id},
            ip=request.client.host if request.client else None,
        )
        db.commit()
    return {"id": target.id, "active": target.is_active}


@router.get("/companies")
def list_companies(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    companies = db.scalars(select(Company).order_by(Company.created_at.desc()).limit(limit).offset(offset)).all()
    return [
        {
            "id": company.id,
            "name": company.name,
            "timezone": company.timezone,
            "daily_limit": company.daily_limit,
            "users": db.scalar(select(func.count(User.id)).where(User.company_id == company.id)) or 0,
            "campaigns": db.scalar(select(func.count(Campaign.id)).where(Campaign.company_id == company.id)) or 0,
            "created_at": company.created_at,
        }
        for company in companies
    ]


@router.patch("/companies/{company_id}/limits")
def update_company_limits(
    company_id: int,
    data: AdminCompanyLimitsUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Empresa não encontrada.")
    company.daily_limit = data.daily_limit
    audit(
        db,
        "admin.company_limit_updated",
        admin,
        "company",
        company.id,
        {"daily_limit": data.daily_limit},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"id": company.id, "daily_limit": company.daily_limit}


@router.get("/campaigns")
def list_campaigns(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Campaign, Company.name)
        .join(Company, Company.id == Campaign.company_id)
        .order_by(Campaign.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {
            "id": campaign.id,
            "company_id": campaign.company_id,
            "company": company_name,
            "name": campaign.internal_name,
            "channel": campaign.channel,
            "status": campaign.status,
            "scheduled_at": campaign.scheduled_at,
            "created_at": campaign.created_at,
        }
        for campaign, company_name in rows
    ]


@router.get("/logs")
def list_logs(
    action: str = Query("", max_length=120),
    company_id: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if company_id:
        stmt = stmt.where(AuditLog.company_id == company_id)
    return [
        {
            "id": row.id,
            "action": row.action,
            "company_id": row.company_id,
            "user_id": row.user_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "date": row.created_at,
        }
        for row in db.scalars(stmt.limit(limit).offset(offset)).all()
    ]


@router.get("/integration-errors")
def list_integration_errors(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Integration, Company.name)
        .join(Company, Company.id == Integration.company_id)
        .where(Integration.last_error.is_not(None))
        .order_by(Integration.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {
            "id": integration.id,
            "company_id": integration.company_id,
            "company": company_name,
            "provider": integration.provider,
            "error": integration.last_error,
            "last_tested_at": integration.last_tested_at,
        }
        for integration, company_name in rows
    ]

