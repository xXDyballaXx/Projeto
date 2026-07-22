import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import (
    ApiCredential,
    AuditLog,
    Campaign,
    CampaignRecipient,
    CampaignStatus,
    Channel,
    Consent,
    Contact,
    ContactList,
    DeliveryEvent,
    GeneratedContent,
    Integration,
    MessageTemplate,
    User,
)
from app.routes import integrations as integration_routes
from app.routes import tracking as tracking_routes
from app.security.crypto import encrypt_secret
from app.services.ai_service import ai_service
from app.services.tracking_service import make_tracking_url


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


def create_facebook_campaign(client, user: dict, name: str) -> dict:
    response = client.post(
        "/api/campaigns",
        headers=user["headers"],
        json={
            "internal_name": name,
            "title": "Oferta rastreavel",
            "body": "Confira a oferta",
            "channel": "facebook",
            "link_url": "https://example.com/oferta",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def content_request(product: str = "Produto seguro") -> dict:
    return {
        "product": product,
        "audience": "Clientes interessados",
        "objective": "Apresentar uma oferta",
        "tone": "profissional",
        "required_information": "Nao inventar descontos",
        "channel": "facebook",
    }


def signed_body(payload: dict, secret: str) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return raw, {
        "content-type": "application/json",
        "x-hub-signature-256": f"sha256={digest}",
    }


def status_payload(phone_number_id: str, external_id: str, state: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "statuses": [{"id": external_id, "status": state}],
                        }
                    }
                ]
            }
        ]
    }


def test_click_tracking_deduplicates_by_campaign_day_ip_and_user_agent(client, monkeypatch):
    owner = register_user(
        client,
        name="Rastreamento",
        company="Empresa Tracking",
        email="tracking-final@example.com",
    )
    campaign_a = create_facebook_campaign(client, owner, "Tracking A")
    campaign_b = create_facebook_campaign(client, owner, "Tracking B")
    path_a = urlsplit(make_tracking_url(campaign_a["id"])).path
    path_b = urlsplit(make_tracking_url(campaign_b["id"])).path
    agent_a = {"user-agent": "Browser-A/1.0"}

    first = client.get(path_a, headers=agent_a, follow_redirects=False)
    duplicate = client.get(path_a, headers=agent_a, follow_redirects=False)
    changed_agent = client.get(
        path_a, headers={"user-agent": "Browser-B/1.0"}, follow_redirects=False
    )
    assert first.status_code == duplicate.status_code == changed_agent.status_code == 302

    with TestClient(
        app,
        client=("198.51.100.27", 51000),
        follow_redirects=False,
    ) as other_ip_client:
        changed_ip = other_ip_client.get(path_a, headers=agent_a)
    assert changed_ip.status_code == 302

    other_campaign = client.get(path_b, headers=agent_a, follow_redirects=False)
    assert other_campaign.status_code == 302

    next_day = datetime.now(timezone.utc) + timedelta(days=1)

    class NextDayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return next_day.replace(tzinfo=None)
            return next_day.astimezone(tz)

    monkeypatch.setattr(tracking_routes, "datetime", NextDayDateTime)
    next_day_click = client.get(path_a, headers=agent_a, follow_redirects=False)
    assert next_day_click.status_code == 302

    with SessionLocal() as db:
        events = db.scalars(
            select(DeliveryEvent)
            .where(DeliveryEvent.event_type == "clicked")
            .order_by(DeliveryEvent.id)
        ).all()
        campaign_a_events = [event for event in events if event.campaign_id == campaign_a["id"]]
        campaign_b_events = [event for event in events if event.campaign_id == campaign_b["id"]]

        assert len(events) == 5
        assert len(campaign_a_events) == 4
        assert len(campaign_b_events) == 1
        assert len({event.external_id for event in events}) == 5
        assert len({event.payload["unique_day"] for event in campaign_a_events}) == 2


def test_whatsapp_template_sync_is_mocked_upserted_and_tenant_scoped(client, monkeypatch):
    owner = register_user(
        client,
        name="Templates A",
        company="Empresa Templates A",
        email="templates-a@example.com",
    )
    outsider = register_user(
        client,
        name="Templates B",
        company="Empresa Templates B",
        email="templates-b@example.com",
    )
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "external_services_enabled", True)

    with SessionLocal() as db:
        integration_a = Integration(
            company_id=owner["company_id"],
            provider="whatsapp",
            is_active=True,
            external_account_id="phone-owner",
            metadata_json={"business_account_id": "waba-owner"},
        )
        integration_b = Integration(
            company_id=outsider["company_id"],
            provider="whatsapp",
            is_active=True,
            external_account_id="phone-outsider",
            metadata_json={"business_account_id": "waba-outsider"},
        )
        db.add_all([integration_a, integration_b])
        db.flush()
        db.add_all(
            [
                ApiCredential(
                    integration_id=integration_a.id,
                    key_name="access_token",
                    encrypted_value=encrypt_secret("token-owner"),
                    masked_hint="****wner",
                ),
                ApiCredential(
                    integration_id=integration_b.id,
                    key_name="access_token",
                    encrypted_value=encrypt_secret("token-outsider"),
                    masked_hint="****ider",
                ),
                MessageTemplate(
                    company_id=owner["company_id"],
                    name="nome_antigo",
                    language="en_US",
                    body="Corpo antigo",
                    meta_template_id="meta-template-1",
                    status="pending",
                ),
                MessageTemplate(
                    company_id=outsider["company_id"],
                    name="template_externo",
                    language="pt_BR",
                    body="Nao pode vazar",
                    meta_template_id="meta-template-foreign",
                    status="approved",
                ),
            ]
        )
        db.commit()
        integration_a_id = integration_a.id
        integration_b_id = integration_b.id

    calls = []
    remote_payload = {
        "data": [
            {
                "id": "meta-template-1",
                "name": "oferta_aprovada",
                "language": "pt_BR",
                "status": "APPROVED",
                "components": [
                    {"type": "HEADER", "text": "Oferta"},
                    {"type": "BODY", "text": "Oferta: {{1}}. Responda SAIR para cancelar."},
                ],
            },
            {
                "id": "meta-template-2",
                "name": "lembrete_pendente",
                "language": "pt_BR",
                "status": "PENDING",
                "components": [{"type": "BODY", "text": "Lembrete {{1}}. Digite SAIR."}],
            },
            {"name": "linha_sem_id", "status": "APPROVED"},
        ]
    }

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return remote_payload

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params, headers):
            calls.append({"url": url, "params": params, "headers": headers, "timeout": self.timeout})
            return MockResponse()

    monkeypatch.setattr(integration_routes.httpx, "AsyncClient", MockAsyncClient)

    first_sync = client.post(
        f"/api/integrations/{integration_a_id}/whatsapp/templates/sync",
        headers=owner["headers"],
    )
    second_sync = client.post(
        f"/api/integrations/{integration_a_id}/whatsapp/templates/sync",
        headers=owner["headers"],
    )
    assert first_sync.status_code == second_sync.status_code == 200
    assert first_sync.json()["synchronized"] is True
    assert first_sync.json()["simulation"] is False
    assert first_sync.json()["count"] == 2
    assert len(calls) == 2
    assert calls[0]["url"].endswith("/waba-owner/message_templates")
    assert calls[0]["headers"] == {"Authorization": "Bearer token-owner"}
    assert calls[0]["params"]["limit"] == 100

    listed = client.get(
        "/api/integrations/whatsapp/message-templates", headers=owner["headers"]
    )
    assert listed.status_code == 200, listed.text
    assert [(row["name"], row["status"]) for row in listed.json()] == [
        ("lembrete_pendente", "pending"),
        ("oferta_aprovada", "approved"),
    ]
    assert all(row["meta_template_id"] != "meta-template-foreign" for row in listed.json())

    foreign_sync = client.post(
        f"/api/integrations/{integration_b_id}/whatsapp/templates/sync",
        headers=owner["headers"],
    )
    assert foreign_sync.status_code == 404, foreign_sync.text

    with SessionLocal() as db:
        owner_templates = db.scalars(
            select(MessageTemplate).where(MessageTemplate.company_id == owner["company_id"])
        ).all()
        synced = next(row for row in owner_templates if row.meta_template_id == "meta-template-1")
        assert len(owner_templates) == 2
        assert synced.name == "oferta_aprovada"
        assert synced.language == "pt_BR"
        assert synced.status == "approved"
        assert "{{1}}" in synced.body
        assert db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.company_id == owner["company_id"],
                AuditLog.action == "integration.templates_synchronized",
            )
        ) == 2


def test_real_whatsapp_campaign_requires_own_approved_compliant_template(client, monkeypatch):
    owner = register_user(
        client,
        name="Campanha real A",
        company="Empresa WhatsApp Real A",
        email="whatsapp-real-a@example.com",
    )
    outsider = register_user(
        client,
        name="Campanha real B",
        company="Empresa WhatsApp Real B",
        email="whatsapp-real-b@example.com",
    )
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "external_services_enabled", True)

    with SessionLocal() as db:
        contact = Contact(
            company_id=owner["company_id"],
            name="Contato com opt-in",
            phone="+5511999997001",
            source="site",
        )
        db.add(contact)
        db.flush()
        db.add(
            Consent(
                contact_id=contact.id,
                channel=Channel.whatsapp,
                source="site",
                is_granted=True,
            )
        )
        contact_list = ContactList(
            company_id=owner["company_id"],
            name="Lista real",
            description="Contatos autorizados",
            contacts=[contact],
        )
        integration = Integration(
            company_id=owner["company_id"],
            provider="whatsapp",
            is_active=True,
            external_account_id="phone-number-real-a",
            metadata_json={"business_account_id": "waba-real-a"},
        )
        pending = MessageTemplate(
            company_id=owner["company_id"],
            name="pendente",
            language="pt_BR",
            body="Oferta {{1}}. Digite SAIR.",
            meta_template_id="pending-1",
            status="pending",
        )
        malformed = MessageTemplate(
            company_id=owner["company_id"],
            name="sem_variavel",
            language="pt_BR",
            body="Oferta fixa. Digite SAIR.",
            meta_template_id="approved-malformed",
            status="approved",
        )
        approved = MessageTemplate(
            company_id=owner["company_id"],
            name="oferta_aprovada",
            language="pt_BR",
            body="Oferta {{1}}. Responda SAIR para cancelar.",
            meta_template_id="approved-owner",
            status="approved",
        )
        foreign = MessageTemplate(
            company_id=outsider["company_id"],
            name="template_estrangeiro",
            language="pt_BR",
            body="Oferta {{1}}. Responda SAIR.",
            meta_template_id="approved-foreign",
            status="approved",
        )
        db.add_all([contact_list, integration, pending, malformed, approved, foreign])
        db.flush()
        db.add(
            ApiCredential(
                integration_id=integration.id,
                key_name="access_token",
                encrypted_value=encrypt_secret("token-real-owner"),
                masked_hint="****wner",
            )
        )
        db.commit()
        ids = {
            "list": contact_list.id,
            "pending": pending.id,
            "malformed": malformed.id,
            "approved": approved.id,
            "foreign": foreign.id,
        }

    base_campaign = {
        "internal_name": "Campanha oficial",
        "title": "Oferta oficial",
        "body": "Texto revisado por uma pessoa",
        "channel": "whatsapp",
        "contact_list_id": ids["list"],
    }

    missing = client.post("/api/campaigns", json=base_campaign, headers=owner["headers"])
    pending = client.post(
        "/api/campaigns",
        json={**base_campaign, "message_template_id": ids["pending"]},
        headers=owner["headers"],
    )
    foreign = client.post(
        "/api/campaigns",
        json={**base_campaign, "message_template_id": ids["foreign"]},
        headers=owner["headers"],
    )
    malformed = client.post(
        "/api/campaigns",
        json={**base_campaign, "message_template_id": ids["malformed"]},
        headers=owner["headers"],
    )
    accepted = client.post(
        "/api/campaigns",
        json={**base_campaign, "message_template_id": ids["approved"]},
        headers=owner["headers"],
    )

    assert missing.status_code == 422, missing.text
    assert "template" in missing.json()["detail"].casefold()
    assert pending.status_code == 422, pending.text
    assert foreign.status_code == 422, foreign.text
    assert malformed.status_code == 422, malformed.text
    assert "{{1}}" in malformed.json()["detail"]
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["message_template_id"] == ids["approved"]

    with SessionLocal() as db:
        campaigns = db.scalars(
            select(Campaign).where(Campaign.company_id == owner["company_id"])
        ).all()
        assert len(campaigns) == 1
        assert campaigns[0].message_template_id == ids["approved"]


def test_daily_ai_quota_is_counted_per_tenant(client, monkeypatch):
    owner = register_user(
        client,
        name="IA diaria A",
        company="Empresa IA diaria A",
        email="ia-diaria-a@example.com",
    )
    other = register_user(
        client,
        name="IA diaria B",
        company="Empresa IA diaria B",
        email="ia-diaria-b@example.com",
    )
    monkeypatch.setattr(settings, "daily_ai_generation_limit", 1)
    monkeypatch.setattr(settings, "minute_ai_generation_limit", 100)

    with SessionLocal() as db:
        db.add(
            GeneratedContent(
                company_id=owner["company_id"],
                user_id=owner["id"],
                prompt_data={},
                content="Geracao ja contabilizada",
                provider="simulation",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    blocked = client.post(
        "/api/content/generate", json=content_request("Produto A"), headers=owner["headers"]
    )
    allowed_other_tenant = client.post(
        "/api/content/generate", json=content_request("Produto B"), headers=other["headers"]
    )
    assert blocked.status_code == 429, blocked.text
    assert "limite" in blocked.json()["detail"].casefold()
    assert allowed_other_tenant.status_code == 200, allowed_other_tenant.text


def test_minute_ai_quota_is_counted_per_tenant(client, monkeypatch):
    owner = register_user(
        client,
        name="IA minuto A",
        company="Empresa IA minuto A",
        email="ia-minuto-a@example.com",
    )
    other = register_user(
        client,
        name="IA minuto B",
        company="Empresa IA minuto B",
        email="ia-minuto-b@example.com",
    )
    monkeypatch.setattr(settings, "daily_ai_generation_limit", 100)
    monkeypatch.setattr(settings, "minute_ai_generation_limit", 1)

    with SessionLocal() as db:
        db.add(
            GeneratedContent(
                company_id=owner["company_id"],
                user_id=owner["id"],
                prompt_data={},
                content="Geracao recente",
                provider="simulation",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    blocked = client.post(
        "/api/content/generate", json=content_request("Produto minuto A"), headers=owner["headers"]
    )
    allowed_other_tenant = client.post(
        "/api/content/generate", json=content_request("Produto minuto B"), headers=other["headers"]
    )
    assert blocked.status_code == 429, blocked.text
    assert "minuto" in blocked.json()["detail"].casefold()
    assert allowed_other_tenant.status_code == 200, allowed_other_tenant.text


def test_real_ai_generation_uses_each_tenants_decrypted_key(client, monkeypatch):
    owner = register_user(
        client,
        name="Chave IA A",
        company="Empresa Chave IA A",
        email="chave-ia-a@example.com",
    )
    other = register_user(
        client,
        name="Chave IA B",
        company="Empresa Chave IA B",
        email="chave-ia-b@example.com",
    )
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "external_services_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", "global-key-must-not-be-used")

    with SessionLocal() as db:
        integrations = []
        for company_id, key in (
            (owner["company_id"], "tenant-key-a"),
            (other["company_id"], "tenant-key-b"),
        ):
            integration = Integration(
                company_id=company_id,
                provider="ai",
                is_active=True,
                metadata_json={},
            )
            db.add(integration)
            db.flush()
            db.add(
                ApiCredential(
                    integration_id=integration.id,
                    key_name="api_key",
                    encrypted_value=encrypt_secret(key),
                    masked_hint="****key",
                )
            )
            integrations.append(integration)
        db.commit()

    observed_keys = []

    async def fake_generate(data, api_key=None):
        observed_keys.append(api_key)
        return f"Conteudo oficial para {data.product}", "official_api"

    monkeypatch.setattr(ai_service, "generate", fake_generate)

    response_a = client.post(
        "/api/content/generate", json=content_request("Produto tenant A"), headers=owner["headers"]
    )
    response_b = client.post(
        "/api/content/generate", json=content_request("Produto tenant B"), headers=other["headers"]
    )

    assert response_a.status_code == response_b.status_code == 200
    assert response_a.json()["provider"] == response_b.json()["provider"] == "official_api"
    assert observed_keys == ["tenant-key-a", "tenant-key-b"]
    assert "global-key-must-not-be-used" not in response_a.text + response_b.text


def test_meta_webhook_rejects_payload_larger_than_two_megabytes(client):
    oversized = b"{" + (b" " * 2_000_000) + b"}"
    response = client.post(
        "/webhooks/meta",
        content=oversized,
        headers={"content-type": "application/json"},
    )

    assert len(oversized) > 2_000_000
    assert response.status_code == 413, response.text


def test_webhook_status_updates_are_monotonic_deduplicated_and_tenant_scoped(client, monkeypatch):
    owner = register_user(
        client,
        name="Webhook A",
        company="Empresa Webhook A",
        email="webhook-status-a@example.com",
    )
    outsider = register_user(
        client,
        name="Webhook B",
        company="Empresa Webhook B",
        email="webhook-status-b@example.com",
    )
    secret = "meta-webhook-secret-final"
    shared_external_id = "wamid-shared-across-tenants"
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "external_services_enabled", True)
    monkeypatch.setattr(settings, "meta_app_secret", secret)

    with SessionLocal() as db:
        user_a = db.get(User, owner["id"])
        user_b = db.get(User, outsider["id"])
        assert user_a is not None and user_b is not None
        contact_a = Contact(
            company_id=owner["company_id"],
            name="Destino A",
            phone="+5511999998101",
            source="teste",
        )
        contact_b = Contact(
            company_id=outsider["company_id"],
            name="Destino B",
            phone="+5511999998102",
            source="teste",
        )
        db.add_all([contact_a, contact_b])
        db.flush()
        campaign_a = Campaign(
            company_id=owner["company_id"],
            created_by_id=user_a.id,
            internal_name="Status webhook A",
            title="A",
            body="Mensagem A",
            channel=Channel.whatsapp,
            status=CampaignStatus.sent,
        )
        campaign_b = Campaign(
            company_id=outsider["company_id"],
            created_by_id=user_b.id,
            internal_name="Status webhook B",
            title="B",
            body="Mensagem B",
            channel=Channel.whatsapp,
            status=CampaignStatus.sent,
        )
        db.add_all([campaign_a, campaign_b])
        db.flush()
        recipient_a = CampaignRecipient(
            campaign_id=campaign_a.id,
            contact_id=contact_a.id,
            status="sent",
            external_message_id=shared_external_id,
            idempotency_key="webhook-status-a",
        )
        recipient_b = CampaignRecipient(
            campaign_id=campaign_b.id,
            contact_id=contact_b.id,
            status="sent",
            external_message_id=shared_external_id,
            idempotency_key="webhook-status-b",
        )
        db.add_all(
            [
                recipient_a,
                recipient_b,
                Integration(
                    company_id=owner["company_id"],
                    provider="whatsapp",
                    external_account_id="phone-webhook-a",
                    is_active=True,
                    metadata_json={},
                ),
                Integration(
                    company_id=outsider["company_id"],
                    provider="whatsapp",
                    external_account_id="phone-webhook-b",
                    is_active=True,
                    metadata_json={},
                ),
            ]
        )
        db.commit()
        ids = {
            "recipient_a": recipient_a.id,
            "recipient_b": recipient_b.id,
            "campaign_a": campaign_a.id,
            "campaign_b": campaign_b.id,
        }

    def post_status(phone_number_id: str, state: str):
        raw, headers = signed_body(
            status_payload(phone_number_id, shared_external_id, state), secret
        )
        return client.post("/webhooks/meta", content=raw, headers=headers)

    delivered = post_status("phone-webhook-a", "delivered")
    duplicate = post_status("phone-webhook-a", "delivered")
    older_status = post_status("phone-webhook-a", "sent")
    read = post_status("phone-webhook-a", "read")
    failed_after_read = post_status("phone-webhook-a", "failed")
    unknown_tenant = post_status("phone-webhook-unknown", "delivered")

    assert delivered.status_code == duplicate.status_code == 200
    assert older_status.status_code == read.status_code == failed_after_read.status_code == 200
    assert unknown_tenant.status_code == 200
    assert delivered.json()["processed"] == 1
    assert duplicate.json()["processed"] == 0
    assert older_status.json()["processed"] == 1
    assert read.json()["processed"] == 1
    assert failed_after_read.json()["processed"] == 1
    assert unknown_tenant.json()["processed"] == 0

    with SessionLocal() as db:
        recipient_a = db.get(CampaignRecipient, ids["recipient_a"])
        recipient_b = db.get(CampaignRecipient, ids["recipient_b"])
        events_a = db.scalars(
            select(DeliveryEvent).where(DeliveryEvent.campaign_id == ids["campaign_a"])
        ).all()
        events_b = db.scalars(
            select(DeliveryEvent).where(DeliveryEvent.campaign_id == ids["campaign_b"])
        ).all()

        assert recipient_a.status == "read"
        assert recipient_b.status == "sent"
        assert {event.event_type for event in events_a} == {
            "sent",
            "delivered",
            "read",
            "failed",
        }
        assert len(events_a) == 4
        assert events_b == []
