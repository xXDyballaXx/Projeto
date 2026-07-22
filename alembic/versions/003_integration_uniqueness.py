"""Impede integrações e credenciais duplicadas por empresa.

Revision ID: 003_integration_unique
Revises: 002_token_version
"""

import sqlalchemy as sa
from alembic import op

revision = "003_integration_unique"
down_revision = "002_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    integration_constraints = {item["name"] for item in inspector.get_unique_constraints("integrations")}
    credential_constraints = {item["name"] for item in inspector.get_unique_constraints("api_credentials")}

    if "uq_integration_company_provider" not in integration_constraints:
        # Older builds could create duplicates under concurrent requests. Keep
        # the newest effective configuration and move non-conflicting secrets.
        groups = bind.execute(sa.text(
            "SELECT company_id, provider FROM integrations "
            "GROUP BY company_id, provider HAVING COUNT(*) > 1"
        )).all()
        for company_id, provider in groups:
            integration_ids = [row[0] for row in bind.execute(
                sa.text(
                    "SELECT id FROM integrations WHERE company_id=:company_id AND provider=:provider "
                    "ORDER BY updated_at DESC, id DESC"
                ),
                {"company_id": company_id, "provider": provider},
            ).all()]
            keep_id, duplicate_ids = integration_ids[0], integration_ids[1:]
            for duplicate_id in duplicate_ids:
                credentials = bind.execute(
                    sa.text("SELECT id, key_name FROM api_credentials WHERE integration_id=:integration_id ORDER BY updated_at DESC, id DESC"),
                    {"integration_id": duplicate_id},
                ).all()
                for credential_id, key_name in credentials:
                    existing = bind.execute(
                        sa.text("SELECT id FROM api_credentials WHERE integration_id=:integration_id AND key_name=:key_name"),
                        {"integration_id": keep_id, "key_name": key_name},
                    ).first()
                    if existing:
                        bind.execute(sa.text("DELETE FROM api_credentials WHERE id=:id"), {"id": credential_id})
                    else:
                        bind.execute(
                            sa.text("UPDATE api_credentials SET integration_id=:keep_id WHERE id=:id"),
                            {"keep_id": keep_id, "id": credential_id},
                        )
                bind.execute(sa.text("DELETE FROM integrations WHERE id=:id"), {"id": duplicate_id})
        with op.batch_alter_table("integrations") as batch_op:
            batch_op.create_unique_constraint(
                "uq_integration_company_provider",
                ["company_id", "provider"],
            )

    if "uq_credential_integration_key" not in credential_constraints:
        duplicate_credentials = bind.execute(sa.text(
            "SELECT integration_id, key_name FROM api_credentials "
            "GROUP BY integration_id, key_name HAVING COUNT(*) > 1"
        )).all()
        for integration_id, key_name in duplicate_credentials:
            ids = [row[0] for row in bind.execute(
                sa.text(
                    "SELECT id FROM api_credentials WHERE integration_id=:integration_id AND key_name=:key_name "
                    "ORDER BY updated_at DESC, id DESC"
                ),
                {"integration_id": integration_id, "key_name": key_name},
            ).all()]
            for credential_id in ids[1:]:
                bind.execute(sa.text("DELETE FROM api_credentials WHERE id=:id"), {"id": credential_id})
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.create_unique_constraint(
                "uq_credential_integration_key",
                ["integration_id", "key_name"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    credential_constraints = {item["name"] for item in inspector.get_unique_constraints("api_credentials")}
    integration_constraints = {item["name"] for item in inspector.get_unique_constraints("integrations")}
    if "uq_credential_integration_key" in credential_constraints:
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.drop_constraint("uq_credential_integration_key", type_="unique")
    if "uq_integration_company_provider" in integration_constraints:
        with op.batch_alter_table("integrations") as batch_op:
            batch_op.drop_constraint("uq_integration_company_provider", type_="unique")
