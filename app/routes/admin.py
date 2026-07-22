from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, Campaign, Company, Contact, Integration, User
from app.security.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["Administração"])


@router.get("/overview")
def overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "companies": db.scalar(select(func.count(Company.id))) or 0,
        "campaigns": db.scalar(select(func.count(Campaign.id))) or 0,
        "blocked_contacts": db.scalar(select(func.count(Contact.id)).where(Contact.permanently_blocked.is_(True))) or 0,
        "integrations": db.scalar(select(func.count(Integration.id))) or 0,
        "recent_logs": [{"action": row.action, "date": row.created_at, "company_id": row.company_id} for row in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(50)).all()],
    }

