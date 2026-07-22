import logging
from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiCredential, Integration
from app.security.crypto import decrypt_secret

logger = logging.getLogger("divulgai.integrations")


@dataclass(slots=True)
class CompanyIntegration:
    integration: Integration | None = None
    credentials: dict[str, str] = field(default_factory=dict)

    @property
    def external_account_id(self) -> str | None:
        return self.integration.external_account_id if self.integration else None

    @property
    def active(self) -> bool:
        return bool(self.integration and self.integration.is_active)


def load_company_integration(db: Session, company_id: int, provider: str) -> CompanyIntegration:
    integration = db.scalar(
        select(Integration)
        .where(Integration.company_id == company_id, Integration.provider == provider)
        .order_by(Integration.updated_at.desc(), Integration.id.desc())
    )
    if not integration:
        return CompanyIntegration()

    values: dict[str, str] = {}
    rows = db.scalars(
        select(ApiCredential)
        .where(ApiCredential.integration_id == integration.id)
        .order_by(ApiCredential.updated_at.desc(), ApiCredential.id.desc())
    ).all()
    for row in rows:
        if row.key_name in values:
            continue
        try:
            values[row.key_name] = decrypt_secret(row.encrypted_value)
        except (InvalidToken, ValueError, TypeError):
            logger.warning(
                "Credencial inválida ignorada integration_id=%s key=%s",
                integration.id,
                row.key_name,
            )
    return CompanyIntegration(integration=integration, credentials=values)

