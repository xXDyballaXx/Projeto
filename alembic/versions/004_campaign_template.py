"""Permite selecionar o template oficial em campanhas WhatsApp.

Revision ID: 004_campaign_template
Revises: 003_integration_unique
"""

import sqlalchemy as sa
from alembic import op

revision = "004_campaign_template"
down_revision = "003_integration_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "message_template_id" in {column["name"] for column in sa.inspect(bind).get_columns("campaigns")}:
        return
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("message_template_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_campaign_message_template",
            "message_templates",
            ["message_template_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "message_template_id" not in {column["name"] for column in sa.inspect(bind).get_columns("campaigns")}:
        return
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_constraint("fk_campaign_message_template", type_="foreignkey")
        batch_op.drop_column("message_template_id")
