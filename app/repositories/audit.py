from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(db: Session, action: str, user: User | None = None, entity_type: str | None = None, entity_id=None, details=None, ip=None):
    db.add(AuditLog(
        company_id=user.company_id if user else None,
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
        ip_address=ip,
    ))
