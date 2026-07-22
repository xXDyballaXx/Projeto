import httpx
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Campaign,
    CampaignRecipient,
    CampaignStatus,
    Consent,
    DeliveryEvent,
    GeneratedContent,
    ScheduledTask,
    UnsubscribeRequest,
)
from app.tasks.campaign_tasks import dispatch_due


class ExternalNetworkForbidden(AssertionError):
    pass


class ForbiddenAsyncClient:
    def __init__(self, *args, **kwargs):
        raise ExternalNetworkForbidden("O fluxo E2E em modo de teste não pode acessar serviços externos.")


def assert_success(response, expected_status=200):
    assert response.status_code == expected_status, response.text
    return response.json()


def test_complete_simulated_marketing_flow(client, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", ForbiddenAsyncClient)
    assert settings.environment == "test"
    assert settings.celery_task_always_eager is True
    assert settings.external_services_enabled is False

    registration = assert_success(
        client.post(
            "/api/auth/register",
            json={
                "name": "Marina Inicial",
                "company_name": "Empresa Fluxo Inicial",
                "email": "marina.fluxo@example.com",
                "password": "SenhaSegura123",
                "password_confirmation": "SenhaSegura123",
                "accept_terms": True,
            },
        ),
        201,
    )
    assert registration["access_token"]
    assert registration["refresh_token"]

    assert_success(client.post("/api/auth/logout"))
    assert client.get("/api/settings/profile").status_code == 401
    login = assert_success(
        client.post(
            "/api/auth/login",
            json={"email": "marina.fluxo@example.com", "password": "SenhaSegura123"},
        )
    )
    assert login["access_token"]

    assert_success(
        client.patch(
            "/api/settings/profile",
            json={
                "name": "Marina Responsável",
                "company": "Empresa Fluxo Completo",
                "timezone": "America/Sao_Paulo",
                "daily_limit": 250,
                "unsubscribe_policy": "Cancelar imediatamente quando o titular solicitar.",
                "sending_preferences": {"responsible_marketing": True},
            },
        )
    )
    profile = assert_success(client.get("/api/settings/profile"))
    assert profile["name"] == "Marina Responsável"
    assert profile["email"] == "marina.fluxo@example.com"
    assert profile["company"] == "Empresa Fluxo Completo"
    assert profile["timezone"] == "America/Sao_Paulo"
    assert profile["daily_limit"] == 250
    assert profile["unsubscribe_policy"] == "Cancelar imediatamente quando o titular solicitar."
    assert profile["sending_preferences"] == {"responsible_marketing": True}
    assert profile["role"] == "user"

    contact = assert_success(
        client.post(
            "/api/contacts",
            json={
                "name": "Cliente com consentimento",
                "phone": "+5511999994321",
                "email": "cliente.fluxo@example.com",
                "source": "formulário E2E",
                "consents": [],
            },
        ),
        201,
    )
    assert contact["consents"] == []
    assert_success(
        client.post(
            f"/api/contacts/{contact['id']}/consents",
            json={
                "channel": "whatsapp",
                "is_granted": True,
                "source": "checkbox explícito no fluxo E2E",
                "proof": "Registro automatizado de autorização",
            },
        )
    )
    contact = next(
        item
        for item in assert_success(client.get("/api/contacts"))
        if item["id"] == contact["id"]
    )
    assert len(contact["consents"]) == 1
    assert contact["consents"][0]["channel"] == "whatsapp"
    assert contact["consents"][0]["is_granted"] is True

    contact_list = assert_success(
        client.post(
            "/api/contacts/lists",
            json={
                "name": "Lista autorizada E2E",
                "description": "Somente contatos com autorização explícita",
                "contact_ids": [contact["id"]],
            },
        ),
        201,
    )
    assert contact_list["contacts"] == 1
    saved_list = assert_success(client.get(f"/api/contacts/lists/{contact_list['id']}"))
    assert saved_list["contact_ids"] == [contact["id"]]

    generated = assert_success(
        client.post(
            "/api/content/generate",
            json={
                "product": "Consultoria responsável",
                "audience": "Pequenas empresas",
                "objective": "apresentar uma solução sem promessas enganosas",
                "tone": "acolhedor",
                "required_information": "Atendimento mediante agendamento.",
                "channel": "whatsapp",
            },
        )
    )
    assert generated["provider"] == "simulation"
    assert generated["requires_human_approval"] is True
    assert "SIMULAÇÃO" in generated["content"]

    approved_text = (
        "Versão revisada pela equipe: conheça nossa consultoria responsável para pequenas empresas. "
        "Atendimento mediante agendamento e sem promessas de resultado."
    )
    approval = assert_success(
        client.post(
            f"/api/content/{generated['id']}/approve",
            json={"content": approved_text},
        )
    )
    assert approval["status"] == "approved"
    assert approval["content"] == approved_text

    campaign_payload = {
        "internal_name": "Campanha WhatsApp E2E",
        "title": "Consultoria para pequenas empresas",
        "body": approved_text,
        "channel": "whatsapp",
        "contact_list_id": contact_list["id"],
        "timezone": "America/Sao_Paulo",
    }
    campaign = assert_success(client.post("/api/campaigns", json=campaign_payload), 201)
    assert campaign["status"] == "draft"
    assert campaign["scheduled_at"] is None

    edited_body = approved_text + " Responda SAIR a qualquer momento para cancelar."
    campaign = assert_success(
        client.patch(
            f"/api/campaigns/{campaign['id']}",
            json={
                "internal_name": "Campanha WhatsApp E2E revisada",
                "title": "Consultoria responsável",
                "body": edited_body,
                "call_to_action": "Converse com nossa equipe",
                "link_url": "https://example.com/consultoria",
            },
        )
    )
    assert campaign["status"] == "draft"
    assert campaign["body"] == edited_body
    assert campaign["call_to_action"] == "Converse com nossa equipe"

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    campaign = assert_success(
        client.patch(
            f"/api/campaigns/{campaign['id']}",
            json={"scheduled_at": future.isoformat()},
        )
    )
    assert campaign["status"] == "scheduled"
    assert campaign["scheduled_at"] is not None

    # Keep a second draft created while consent is valid. It will prove that a
    # later opt-out blocks a genuinely new processing attempt.
    blocked_draft_payload = dict(campaign_payload)
    blocked_draft_payload["internal_name"] = "Campanha posterior ao opt-out"
    blocked_draft = assert_success(client.post("/api/campaigns", json=blocked_draft_payload), 201)
    assert blocked_draft["status"] == "draft"

    due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    with SessionLocal() as db:
        saved_campaign = db.get(Campaign, campaign["id"])
        scheduled_task = db.scalar(
            select(ScheduledTask).where(
                ScheduledTask.campaign_id == campaign["id"],
                ScheduledTask.status == "pending",
            )
        )
        assert scheduled_task is not None
        saved_campaign.scheduled_at = due_at
        scheduled_task.execute_at = due_at
        db.commit()
        scheduled_task_id = scheduled_task.id

    dispatch_result = dispatch_due.delay()
    assert dispatch_result.successful(), dispatch_result.result
    assert dispatch_result.result == {"dispatched": 1}

    with SessionLocal() as db:
        saved_campaign = db.get(Campaign, campaign["id"])
        scheduled_task = db.get(ScheduledTask, scheduled_task_id)
        recipient = db.scalar(
            select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign["id"])
        )
        generated_content = db.get(GeneratedContent, generated["id"])
        simulated_events = db.scalar(
            select(func.count(DeliveryEvent.id)).where(
                DeliveryEvent.campaign_id == campaign["id"],
                DeliveryEvent.event_type == "simulated",
            )
        )

        assert saved_campaign.status == CampaignStatus.simulated
        assert scheduled_task.status == "completed"
        assert scheduled_task.attempts == 1
        assert scheduled_task.result["status"] == "simulated"
        assert recipient is not None
        assert recipient.status == "simulated"
        assert recipient.external_message_id is None
        assert simulated_events == 1
        assert generated_content.status == "approved"
        assert generated_content.content == approved_text

    history = assert_success(client.get("/api/campaigns/history/all"))
    history_item = next(item for item in history if item["id"] == campaign["id"])
    assert history_item["campaign"] == "Campanha WhatsApp E2E revisada"
    assert history_item["channel"] == "whatsapp"
    assert history_item["status"] == "simulated"
    assert history_item["recipients"] == 1
    assert history_item["sent"] == 0
    assert history_item["failures"] == 0

    revoked = assert_success(
        client.post(
            f"/api/contacts/{contact['id']}/consents",
            json={
                "channel": "whatsapp",
                "is_granted": False,
                "source": "solicitação do titular no fluxo E2E",
                "proof": "Opt-out confirmado",
            },
        )
    )
    assert not any(
        item["is_granted"] and item["revoked_at"] is None
        for item in revoked["consents"]
        if item["channel"] == "whatsapp"
    )

    blocked_send = client.post(f"/api/campaigns/{blocked_draft['id']}/send")
    assert blocked_send.status_code in {200, 409, 422}, blocked_send.text
    if blocked_send.status_code == 200:
        blocked_result = blocked_send.json()["result"]
        assert blocked_result["status"] == "failed"
        assert "consentimento" in blocked_result["reason"].casefold()
    else:
        assert "consentimento" in blocked_send.json()["detail"].casefold()

    rejected_campaign_payload = dict(campaign_payload)
    rejected_campaign_payload["internal_name"] = "Nova campanha sem consentimento"
    rejected_campaign = client.post("/api/campaigns", json=rejected_campaign_payload)
    assert rejected_campaign.status_code == 422, rejected_campaign.text
    assert "consentimento" in rejected_campaign.json()["detail"].casefold()

    with SessionLocal() as db:
        blocked_campaign = db.get(Campaign, blocked_draft["id"])
        blocked_recipients = db.scalar(
            select(func.count(CampaignRecipient.id)).where(
                CampaignRecipient.campaign_id == blocked_draft["id"]
            )
        )
        unsubscribe_requests = db.scalar(
            select(func.count(UnsubscribeRequest.id)).where(
                UnsubscribeRequest.contact_id == contact["id"]
            )
        )
        latest_consent = db.scalar(
            select(Consent)
            .where(Consent.contact_id == contact["id"])
            .order_by(Consent.created_at.desc(), Consent.id.desc())
        )

        assert blocked_campaign.status in {CampaignStatus.draft, CampaignStatus.failed}
        assert blocked_recipients == 0
        assert unsubscribe_requests == 1
        assert latest_consent.is_granted is False
        assert latest_consent.revoked_at is not None
        assert db.scalar(select(func.count(Campaign.id))) == 2
