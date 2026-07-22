from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    AuditLog,
    Campaign,
    CampaignRecipient,
    CampaignStatus,
    Channel,
    Contact,
    DeliveryEvent,
    Integration,
    Role,
    User,
)


def register_user(client, *, name: str, company: str, email: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "name": name,
            "company_name": company,
            "email": email,
            "password": "Senha123",
            "password_confirmation": "Senha123",
            "accept_terms": True,
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        return {
            "id": user.id,
            "company_id": user.company_id,
            "token": token,
            "headers": {"Authorization": f"Bearer {token}"},
        }


def promote_to_admin(user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = Role.admin
        db.commit()


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/api/admin/overview", None),
        ("get", "/api/admin/users", None),
        ("get", "/api/admin/companies", None),
        ("get", "/api/admin/campaigns", None),
        ("get", "/api/admin/logs", None),
        ("get", "/api/admin/integration-errors", None),
        ("patch", "/api/admin/users/1", {"is_active": False}),
        ("patch", "/api/admin/companies/1/limits", {"daily_limit": 50}),
    ],
)
def test_every_admin_endpoint_requires_an_authenticated_admin(client, method, path, json_body):
    regular = register_user(
        client,
        name="Usuario comum",
        company="Empresa comum",
        email="comum-admin-check@example.com",
    )
    client.cookies.clear()

    unauthenticated = client.request(method, path, json=json_body)
    regular_user = client.request(method, path, json=json_body, headers=regular["headers"])

    assert unauthenticated.status_code == 401, unauthenticated.text
    assert regular_user.status_code == 403, regular_user.text


def test_admin_can_manage_users_limits_and_inspect_global_operations(client):
    admin = register_user(
        client,
        name="Administradora",
        company="Operacao Central",
        email="admin-final@example.com",
    )
    target = register_user(
        client,
        name="Marina Alvo",
        company="Loja da Marina",
        email="marina.alvo@example.com",
    )
    other = register_user(
        client,
        name="Outro usuario",
        company="Empresa sem erro",
        email="outro.final@example.com",
    )
    promote_to_admin(admin["id"])

    with SessionLocal() as db:
        target_user = db.get(User, target["id"])
        other_user = db.get(User, other["id"])
        assert target_user is not None and other_user is not None
        target_campaign = Campaign(
            company_id=target_user.company_id,
            created_by_id=target_user.id,
            internal_name="Campanha visivel ao admin",
            title="Oferta",
            body="Corpo da oferta",
            channel=Channel.facebook,
            status=CampaignStatus.failed,
        )
        db.add_all(
            [
                target_campaign,
                Integration(
                    company_id=target_user.company_id,
                    provider="whatsapp",
                    external_account_id="identificador-que-nao-deve-vazar",
                    is_active=False,
                    last_error="Token recusado pela Meta",
                ),
                Integration(
                    company_id=other_user.company_id,
                    provider="ai",
                    is_active=True,
                    last_error=None,
                ),
                AuditLog(
                    company_id=target_user.company_id,
                    user_id=target_user.id,
                    action="integration.connection_failed",
                    entity_type="integration",
                    entity_id="wa-final",
                    details={"safe": True},
                ),
            ]
        )
        db.commit()
        target_campaign_id = target_campaign.id

    headers = admin["headers"]

    users = client.get(
        "/api/admin/users",
        params={"q": "marina.alvo", "limit": 1, "offset": 0},
        headers=headers,
    )
    assert users.status_code == 200, users.text
    assert [(row["id"], row["company"]) for row in users.json()] == [
        (target["id"], "Loja da Marina")
    ]

    blocked = client.patch(
        f"/api/admin/users/{target['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json() == {"id": target["id"], "active": False}
    assert client.get("/api/contacts", headers=target["headers"]).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "marina.alvo@example.com", "password": "Senha123"},
    ).status_code == 403

    self_block = client.patch(
        f"/api/admin/users/{admin['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert self_block.status_code == 409, self_block.text

    unblocked = client.patch(
        f"/api/admin/users/{target['id']}",
        json={"is_active": True},
        headers=headers,
    )
    assert unblocked.status_code == 200, unblocked.text
    assert client.post(
        "/api/auth/login",
        json={"email": "marina.alvo@example.com", "password": "Senha123"},
    ).status_code == 200

    companies = client.get("/api/admin/companies", headers=headers)
    assert companies.status_code == 200, companies.text
    target_company = next(row for row in companies.json() if row["id"] == target["company_id"])
    assert target_company["users"] == 1
    assert target_company["campaigns"] == 1

    limit_update = client.patch(
        f"/api/admin/companies/{target['company_id']}/limits",
        json={"daily_limit": 321},
        headers=headers,
    )
    assert limit_update.status_code == 200, limit_update.text
    assert limit_update.json() == {"id": target["company_id"], "daily_limit": 321}

    campaigns = client.get("/api/admin/campaigns", headers=headers)
    assert campaigns.status_code == 200, campaigns.text
    campaign_row = next(row for row in campaigns.json() if row["id"] == target_campaign_id)
    assert campaign_row["company_id"] == target["company_id"]
    assert campaign_row["company"] == "Loja da Marina"
    assert campaign_row["status"] == "failed"

    logs = client.get(
        "/api/admin/logs",
        params={"action": "integration.connection", "company_id": target["company_id"]},
        headers=headers,
    )
    assert logs.status_code == 200, logs.text
    assert [row["action"] for row in logs.json()] == ["integration.connection_failed"]
    assert all(row["company_id"] == target["company_id"] for row in logs.json())

    errors = client.get("/api/admin/integration-errors", headers=headers)
    assert errors.status_code == 200, errors.text
    assert len(errors.json()) == 1
    assert errors.json()[0]["company_id"] == target["company_id"]
    assert errors.json()[0]["company"] == "Loja da Marina"
    assert errors.json()[0]["provider"] == "whatsapp"
    assert errors.json()[0]["error"] == "Token recusado pela Meta"
    assert "identificador-que-nao-deve-vazar" not in errors.text

    overview = client.get("/api/admin/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    assert overview.json()["users"] == 3
    assert overview.json()["companies"] == 3
    assert overview.json()["campaigns"] == 1
    assert overview.json()["integrations"] == 2

    with SessionLocal() as db:
        target_user = db.get(User, target["id"])
        company = target_user.company
        admin_actions = set(
            db.scalars(select(AuditLog.action).where(AuditLog.user_id == admin["id"])).all()
        )
        assert target_user.is_active is True
        assert target_user.token_version == 2
        assert company.daily_limit == 321
        assert {
            "admin.user_blocked",
            "admin.user_unblocked",
            "admin.company_limit_updated",
        }.issubset(admin_actions)


def test_admin_mutations_validate_targets_and_limit_bounds(client):
    admin = register_user(
        client,
        name="Admin validacao",
        company="Central validacao",
        email="admin-validacao@example.com",
    )
    promote_to_admin(admin["id"])

    assert client.patch(
        "/api/admin/users/999999",
        json={"is_active": False},
        headers=admin["headers"],
    ).status_code == 404
    assert client.patch(
        "/api/admin/companies/999999/limits",
        json={"daily_limit": 10},
        headers=admin["headers"],
    ).status_code == 404
    assert client.patch(
        f"/api/admin/companies/{admin['company_id']}/limits",
        json={"daily_limit": 0},
        headers=admin["headers"],
    ).status_code == 422


def test_history_filters_paginates_details_and_isolates_tenants(client):
    owner = register_user(
        client,
        name="Dona do historico",
        company="Empresa Historico A",
        email="historico-a@example.com",
    )
    outsider = register_user(
        client,
        name="Outra empresa",
        company="Empresa Historico B",
        email="historico-b@example.com",
    )
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        owner_user = db.get(User, owner["id"])
        outsider_user = db.get(User, outsider["id"])
        assert owner_user is not None and outsider_user is not None
        contact_one = Contact(
            company_id=owner_user.company_id,
            name="Contato entregue",
            phone="+5511999990001",
            source="teste",
        )
        contact_two = Contact(
            company_id=owner_user.company_id,
            name="Contato bloqueado",
            phone="+5511999990002",
            source="teste",
        )
        db.add_all([contact_one, contact_two])
        db.flush()

        old_campaign = Campaign(
            company_id=owner_user.company_id,
            created_by_id=owner_user.id,
            internal_name="Arquivo antigo",
            title="Antiga",
            body="Finalizada antes",
            channel=Channel.instagram,
            status=CampaignStatus.simulated,
            created_at=now - timedelta(minutes=5),
        )
        failed_campaign = Campaign(
            company_id=owner_user.company_id,
            created_by_id=owner_user.id,
            internal_name="Falha segmentada",
            title="Falha",
            body="Campanha com falha",
            channel=Channel.whatsapp,
            status=CampaignStatus.failed,
            created_at=now - timedelta(minutes=4),
        )
        sent_campaign = Campaign(
            company_id=owner_user.company_id,
            created_by_id=owner_user.id,
            internal_name="Boletim final entregue",
            title="Boletim",
            body="Conteudo entregue",
            channel=Channel.facebook,
            status=CampaignStatus.sent,
            created_at=now - timedelta(minutes=3),
        )
        draft_campaign = Campaign(
            company_id=owner_user.company_id,
            created_by_id=owner_user.id,
            internal_name="Rascunho recente",
            title="Rascunho",
            body="Ainda nao finalizado",
            channel=Channel.facebook,
            status=CampaignStatus.draft,
            created_at=now - timedelta(minutes=2),
        )
        foreign_campaign = Campaign(
            company_id=outsider_user.company_id,
            created_by_id=outsider_user.id,
            internal_name="Boletim de outra empresa",
            title="Externo",
            body="Nao deve aparecer",
            channel=Channel.facebook,
            status=CampaignStatus.sent,
            created_at=now - timedelta(minutes=1),
        )
        db.add_all(
            [old_campaign, failed_campaign, sent_campaign, draft_campaign, foreign_campaign]
        )
        db.flush()
        delivered_recipient = CampaignRecipient(
            campaign_id=sent_campaign.id,
            contact_id=contact_one.id,
            status="delivered",
            external_message_id="wamid-history-delivered",
            idempotency_key="history-delivered",
        )
        blocked_recipient = CampaignRecipient(
            campaign_id=failed_campaign.id,
            contact_id=contact_two.id,
            status="blocked",
            error_message="Consentimento revogado",
            idempotency_key="history-blocked",
        )
        db.add_all([delivered_recipient, blocked_recipient])
        db.flush()
        db.add_all(
            [
                DeliveryEvent(
                    campaign_id=sent_campaign.id,
                    recipient_id=delivered_recipient.id,
                    external_id="wamid-history-delivered",
                    event_type="delivered",
                    payload={},
                    occurred_at=now - timedelta(minutes=2),
                ),
                DeliveryEvent(
                    campaign_id=sent_campaign.id,
                    external_id="click-history",
                    event_type="clicked",
                    payload={},
                    occurred_at=now - timedelta(minutes=1),
                ),
            ]
        )
        db.commit()
        ids = {
            "old": old_campaign.id,
            "failed": failed_campaign.id,
            "sent": sent_campaign.id,
            "draft": draft_campaign.id,
            "foreign": foreign_campaign.id,
        }

    headers = owner["headers"]
    first_page = client.get(
        "/api/campaigns/history/all",
        params={"limit": 2, "offset": 0},
        headers=headers,
    )
    assert first_page.status_code == 200, first_page.text
    assert [row["id"] for row in first_page.json()] == [ids["sent"], ids["failed"]]
    assert all(row["id"] not in {ids["draft"], ids["foreign"]} for row in first_page.json())

    second_item = client.get(
        "/api/campaigns/history/all",
        params={"limit": 1, "offset": 1},
        headers=headers,
    )
    assert second_item.status_code == 200, second_item.text
    assert [row["id"] for row in second_item.json()] == [ids["failed"]]
    assert second_item.json()[0]["recipients"] == 1
    assert second_item.json()[0]["failures"] == 1

    by_query = client.get(
        "/api/campaigns/history/all", params={"q": "boletim final"}, headers=headers
    )
    assert [row["id"] for row in by_query.json()] == [ids["sent"]]
    assert by_query.json()[0]["sent"] == 1

    by_channel = client.get(
        "/api/campaigns/history/all", params={"channel": "whatsapp"}, headers=headers
    )
    assert [row["id"] for row in by_channel.json()] == [ids["failed"]]

    by_status = client.get(
        "/api/campaigns/history/all", params={"status": "simulated"}, headers=headers
    )
    assert [row["id"] for row in by_status.json()] == [ids["old"]]

    nonterminal_filter = client.get(
        "/api/campaigns/history/all", params={"status": "draft"}, headers=headers
    )
    assert nonterminal_filter.status_code == 422, nonterminal_filter.text

    detail = client.get(f"/api/campaigns/history/{ids['sent']}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == ids["sent"]
    assert body["name"] == "Boletim final entregue"
    assert body["recipients"] == [
        {
            "id": body["recipients"][0]["id"],
            "status": "delivered",
            "external_message_id": "wamid-history-delivered",
            "error": None,
        }
    ]
    assert [event["type"] for event in body["events"]] == ["clicked", "delivered"]

    assert client.get(
        f"/api/campaigns/history/{ids['draft']}", headers=headers
    ).status_code == 404
    assert client.get(
        f"/api/campaigns/history/{ids['foreign']}", headers=headers
    ).status_code == 404

