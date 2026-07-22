"""Esquema inicial completo.

Revision ID: 001_initial
Revises:
"""
from alembic import op

from app.database import Base
from app import models  # noqa: F401

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Usa os mesmos metadados declarativos auditados pela aplicação. Novas alterações
    # devem ser geradas com `alembic revision --autogenerate`.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

