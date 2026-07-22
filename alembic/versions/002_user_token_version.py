"""Adiciona versão revogável às sessões JWT.

Revision ID: 002_token_version
Revises: 001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "002_token_version"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "token_version" in {column["name"] for column in sa.inspect(bind).get_columns("users")}:
        return
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "token_version" in {column["name"] for column in sa.inspect(bind).get_columns("users")}:
        op.drop_column("users", "token_version")
