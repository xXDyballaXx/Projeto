import asyncio
import csv
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Campaign,
    CampaignChannel,
    CampaignStatus,
    Channel,
    Company,
    Consent,
    Contact,
    Integration,
    ScheduledTask,
    UnsubscribeRequest,
    User,
)
from app.routes import campaigns as campaign_routes
from app.services.campaign_service import execute_campaign
from app.services.exceptions import IntegrationError
from app.services.facebook_service import facebook_service
from app.services.instagram_service import instagram_service
from app.services.whatsapp_service import whatsapp_service
from app.tasks.campaign_tasks import send_campaign


class NetworkAccessForbidden(AssertionError):
    """Raised when a regression test unexpectedly attempts external I/O."""


class ForbiddenAsyncClient:
    def __init__(self, *args, **kwargs):
        raise NetworkAccessForbidden("ENVIRONMENT=test must never instantiate an external HTTP client.")


class InMemoryUploadPath:
    files = {}

    def __init__(self, *parts):
        self.parts = tuple(str(part) for part in parts)

    def __truediv__(self, part):
        return type(self)(*self.parts, part)

    def __str__(self):
        return "/".join(self.parts)

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.parts == other.parts

    def __hash__(self):
        return hash(self.parts)

    @property
    def name(self):
        return self.parts[-1].replace("\\", "/").rsplit("/", 1)[-1] if self.parts else ""

    @property
    def parent(self):
        return type(self)(*self.parts[:-1])

    def resolve(self):
        return self

    def mkdir(self, *args, **kwargs):
        return None

    def write_bytes(self, content):
        type(self).files[str(self)] = bytes(content)
        return len(content)

    def iterdir(self):
        prefix = f"{self}/"
        for filename in tuple(type(self).files):
            if filename.startswith(prefix) and "/" not in filename[len(prefix):]:
                yield type(self)(*filename.split("/"))

    def is_file(self):
        return str(self) in type(self).files

    def stat(self):
        return SimpleNamespace(st_size=len(type(self).files[str(self)]))

    def unlink(self, missing_ok=False):
        try:
            del type(self).files[str(self)]
        except KeyError:
            if not missing_ok:
                raise FileNotFoundError(str(self))


@pytest.fixture
def in_memory_uploads(monkeypatch):
    InMemoryUploadPath.files = {}
    monkeypatch.setattr(campaign_routes, "Path", InMemoryUploadPath)
    return InMemoryUploadPath.files


def create_facebook_campaign(client, name: str = "Campanha de auditoria") -> dict:
    response = client.post(
        "/api/campaigns",
        json={
            "internal_name": name,
            "title": "Titulo de auditoria",
            "body": "Conteudo seguro para o teste",
            "channel": "facebook",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def signed_webhook_body(payload: dict, secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, f"sha256={digest}"


def test_test_environment_never_calls_external_network_even_with_credentials(monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "test-phone-number-id")
    monkeypatch.setattr(settings, "whatsapp_access_token", "test-whatsapp-token")
    monkeypatch.setattr(settings, "facebook_page_id", "test-facebook-page-id")
    monkeypatch.setattr(settings, "facebook_page_access_token", "test-facebook-token")
    monkeypatch.setattr(settings, "instagram_account_id", "test-instagram-account-id")
    monkeypatch.setattr(httpx, "AsyncClient", ForbiddenAsyncClient)

    async def invoke_services():
        whatsapp = await whatsapp_service.send_template("+5511999999999", "template_de_teste")
        facebook = await facebook_service.publish("Publicacao de teste")
        instagram = await instagram_service.publish_media("https://example.test/image.png", "Legenda de teste")
        return whatsapp, facebook, instagram

    results = asyncio.run(invoke_services())

    assert all(result.simulated for result in results)
    assert all(not result.success for result in results)


def test_real_environment_never_downgrades_missing_tenant_credentials_to_simulation(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "external_services_enabled", True)

    with pytest.raises(IntegrationError):
        asyncio.run(facebook_service.publish("Publicação", page_id="", access_token=""))
    with pytest.raises(IntegrationError):
        asyncio.run(
            instagram_service.publish_media(
                "https://example.test/image.png",
                "Legenda",
                account_id="",
                access_token="",
            )
        )


def test_past_schedule_is_rejected_without_persisting_campaign_or_task(auth):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    response = auth["client"].post(
        "/api/campaigns",
        json={
            "internal_name": "Agendamento no passado",
            "title": "Nao deve persistir",
            "body": "Esta campanha deve sofrer rollback completo.",
            "channel": "facebook",
            "scheduled_at": past,
        },
    )

    assert response.status_code in {400, 422}, response.text
    assert auth["client"].get("/api/campaigns").json() == []
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Campaign.id))) == 0
        assert db.scalar(select(func.count(ScheduledTask.id))) == 0


@pytest.mark.parametrize(
    "terminal_status",
    [CampaignStatus.sending, CampaignStatus.sent, CampaignStatus.simulated],
)
def test_resending_terminal_or_in_progress_campaign_is_blocked(auth, monkeypatch, terminal_status):
    campaign = create_facebook_campaign(auth["client"], f"Reenvio {terminal_status.value}")
    with SessionLocal() as db:
        saved = db.get(Campaign, campaign["id"])
        saved.status = terminal_status
        db.commit()

    delay_calls = []

    def unexpected_delay(campaign_id):
        delay_calls.append(campaign_id)
        return SimpleNamespace(id="unexpected-task", result=None)

    monkeypatch.setattr(send_campaign, "delay", unexpected_delay)
    response = auth["client"].post(f"/api/campaigns/{campaign['id']}/send")

    assert response.status_code == 409, response.text
    assert delay_calls == []
    with SessionLocal() as db:
        assert db.get(Campaign, campaign["id"]).status == terminal_status
        assert db.scalar(select(func.count(ScheduledTask.id))) == 0


def test_simulated_facebook_execution_persists_simulated_status(auth, monkeypatch):
    campaign = create_facebook_campaign(auth["client"], "Facebook simulado")
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "facebook_page_id", "")
    monkeypatch.setattr(settings, "facebook_page_access_token", "")
    monkeypatch.setattr(httpx, "AsyncClient", ForbiddenAsyncClient)

    with SessionLocal() as db:
        result = asyncio.run(execute_campaign(db, campaign["id"]))
        saved = db.get(Campaign, campaign["id"])
        channel = db.scalar(select(CampaignChannel).where(CampaignChannel.campaign_id == campaign["id"]))

        assert result["status"] in {"simulation", "simulated"}
        assert saved.status == CampaignStatus.simulated
        assert channel is not None
        assert channel.status == "simulated"


def test_whatsapp_opt_out_is_tenant_scoped_and_idempotent(auth, monkeypatch):
    client = auth["client"]
    phone = "+5511999990000"
    first_contact = client.post(
        "/api/contacts",
        json={
            "name": "Contato empresa A",
            "phone": phone,
            "source": "site",
            "consents": [{"channel": "whatsapp", "source": "site", "is_granted": True}],
        },
    )
    assert first_contact.status_code == 201, first_contact.text

    with SessionLocal() as db:
        contact_a = db.get(Contact, first_contact.json()["id"])
        company_b = Company(name="Empresa B")
        db.add(company_b)
        db.flush()
        contact_b = Contact(company_id=company_b.id, name="Contato empresa B", phone=phone, source="site")
        db.add(contact_b)
        db.flush()
        db.add(Consent(contact_id=contact_b.id, channel=Channel.whatsapp, source="site", is_granted=True))
        db.add_all(
            [
                Integration(
                    company_id=contact_a.company_id,
                    provider="whatsapp",
                    external_account_id="phone-number-id-company-a",
                    is_active=True,
                ),
                Integration(
                    company_id=company_b.id,
                    provider="whatsapp",
                    external_account_id="phone-number-id-company-b",
                    is_active=True,
                ),
            ]
        )
        db.commit()
        contact_a_id = contact_a.id
        contact_b_id = contact_b.id

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone-number-id-company-a"},
                            "messages": [
                                {
                                    "id": "wamid-optout-company-a-1",
                                    "from": "5511999990000",
                                    "type": "text",
                                    "text": {"body": "SAIR"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    secret = "test-meta-app-secret"
    monkeypatch.setattr(settings, "meta_app_secret", secret)
    body, signature = signed_webhook_body(payload, secret)
    headers = {"content-type": "application/json", "x-hub-signature-256": signature}

    first = client.post("/webhooks/meta", content=body, headers=headers)
    replay = client.post("/webhooks/meta", content=body, headers=headers)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    with SessionLocal() as db:
        consent_a = db.scalar(
            select(Consent)
            .where(Consent.contact_id == contact_a_id, Consent.channel == Channel.whatsapp)
            .order_by(Consent.created_at.desc(), Consent.id.desc())
        )
        consent_b = db.scalar(
            select(Consent)
            .where(Consent.contact_id == contact_b_id, Consent.channel == Channel.whatsapp)
            .order_by(Consent.created_at.desc(), Consent.id.desc())
        )
        requests_a = db.scalar(
            select(func.count(UnsubscribeRequest.id)).where(UnsubscribeRequest.contact_id == contact_a_id)
        )
        requests_b = db.scalar(
            select(func.count(UnsubscribeRequest.id)).where(UnsubscribeRequest.contact_id == contact_b_id)
        )

        assert consent_a.is_granted is False
        assert consent_a.revoked_at is not None
        assert consent_b.is_granted is True
        assert consent_b.revoked_at is None
        assert requests_a == 1
        assert requests_b == 0


def test_signed_webhook_rejects_invalid_entry_shape_without_internal_error(auth, monkeypatch):
    secret = "test-meta-shape-secret"
    monkeypatch.setattr(settings, "meta_app_secret", secret)
    invalid_body, invalid_signature = signed_webhook_body({"entry": {"changes": []}}, secret)

    rejected = auth["client"].post(
        "/webhooks/meta",
        content=invalid_body,
        headers={"content-type": "application/json", "x-hub-signature-256": invalid_signature},
    )

    assert rejected.status_code == 400, rejected.text

    unusual_payload = {
        "entry": [
            None,
            {
                "changes": [
                    None,
                    {
                        "value": {
                            "metadata": [],
                            "statuses": [None, {"id": [], "status": {}}],
                            "messages": [None, {"from": 123, "text": {"body": []}}],
                        }
                    },
                ]
            },
        ]
    }
    unusual_body, unusual_signature = signed_webhook_body(unusual_payload, secret)
    accepted = auth["client"].post(
        "/webhooks/meta",
        content=unusual_body,
        headers={"content-type": "application/json", "x-hub-signature-256": unusual_signature},
    )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"received": True, "processed": 0}


@pytest.mark.parametrize(
    ("first_file", "replacement_file", "cleared_field"),
    [
        (("first.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png"),
         ("replacement.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8, "video/mp4"),
         "image_path"),
        (("first.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8, "video/mp4"),
         ("replacement.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png"),
         "video_path"),
    ],
)
def test_upload_replacement_clears_opposite_media_field(
    auth, in_memory_uploads, first_file, replacement_file, cleared_field
):
    campaign = create_facebook_campaign(auth["client"], f"Troca de midia {cleared_field}")

    first = auth["client"].post(
        f"/api/campaigns/{campaign['id']}/upload",
        files={"file": first_file},
    )
    replacement = auth["client"].post(
        f"/api/campaigns/{campaign['id']}/upload",
        files={"file": replacement_file},
    )

    assert first.status_code == 200, first.text
    assert replacement.status_code == 200, replacement.text
    with SessionLocal() as db:
        saved = db.get(Campaign, campaign["id"])
        assert getattr(saved, cleared_field) is None
        remaining_field = "video_path" if cleared_field == "image_path" else "image_path"
        assert getattr(saved, remaining_field)


def test_upload_replacement_counts_only_the_final_file_against_company_quota(
    auth, in_memory_uploads, monkeypatch
):
    monkeypatch.setattr(settings, "max_company_upload_mb", 0.00003)
    campaign = create_facebook_campaign(auth["client"], "Troca dentro da cota")

    first = auth["client"].post(
        f"/api/campaigns/{campaign['id']}/upload",
        files={"file": ("first.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png")},
    )
    replacement = auth["client"].post(
        f"/api/campaigns/{campaign['id']}/upload",
        files={"file": ("replacement.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8, "video/mp4")},
    )

    assert first.status_code == 200, first.text
    assert replacement.status_code == 200, replacement.text
    assert len(in_memory_uploads) == 1


@pytest.mark.parametrize("terminal_status", [CampaignStatus.sent, CampaignStatus.simulated])
def test_upload_is_blocked_for_completed_campaign(
    auth, in_memory_uploads, terminal_status
):
    campaign = create_facebook_campaign(auth["client"], f"Upload bloqueado {terminal_status.value}")
    with SessionLocal() as db:
        saved = db.get(Campaign, campaign["id"])
        saved.status = terminal_status
        db.commit()

    response = auth["client"].post(
        f"/api/campaigns/{campaign['id']}/upload",
        files={"file": ("blocked.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png")},
    )

    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        saved = db.get(Campaign, campaign["id"])
        assert saved.status == terminal_status
        assert saved.image_path is None
        assert saved.video_path is None


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("empty.csv", b""),
        ("missing-headers.csv", "nome,telefone\nMaria,+5511999999999\n".encode("utf-8")),
        ("invalid-utf8.csv", b"nome,telefone,consentimento,canal,origem\n\xff\xfe"),
    ],
)
def test_invalid_csv_is_rejected_without_partial_persistence(auth, filename, content):
    response = auth["client"].post(
        "/api/contacts/import/csv",
        files={"file": (filename, content, "text/csv")},
    )

    assert response.status_code in {400, 422}, response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Contact.id))) == 0


def test_csv_headers_are_case_insensitive_and_whitespace_tolerant(auth):
    content = (
        " Nome , TELEFONE,Email,Consentimento,CANAL, Origem \n"
        "Maria,+5511999999999,maria@example.com,sim,whatsapp,evento\n"
    ).encode("utf-8")

    response = auth["client"].post(
        "/api/contacts/import/csv",
        files={"file": ("contatos.csv", content, "text/csv")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1


def test_partial_updates_reject_null_for_required_database_fields(auth):
    contact = auth["client"].post(
        "/api/contacts",
        json={"name": "Maria", "phone": "+5511999999999", "source": "manual"},
    ).json()
    contact_list = auth["client"].post(
        "/api/contacts/lists",
        json={"name": "Clientes"},
    ).json()
    campaign = create_facebook_campaign(auth["client"], "Campos obrigatórios")

    assert auth["client"].patch(f"/api/contacts/{contact['id']}", json={"phone": None}).status_code == 422
    assert auth["client"].patch(f"/api/contacts/lists/{contact_list['id']}", json={"name": None}).status_code == 422
    assert auth["client"].patch(f"/api/campaigns/{campaign['id']}", json={"channel": None}).status_code == 422

    with SessionLocal() as db:
        assert db.get(Contact, contact["id"]).phone == "+5511999999999"
        assert db.get(Campaign, campaign["id"]).channel == Channel.facebook


def test_csv_export_escapes_spreadsheet_formula_cells(auth):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "ana@example.com"))
        db.add(
            Contact(
                company_id=user.company_id,
                name="=2+2",
                phone="+5511999999999",
                tags=["-1+1"],
                source="@planilha",
                is_active=True,
            )
        )
        db.commit()

    response = auth["client"].get("/api/contacts/export/csv/all")

    assert response.status_code == 200, response.text
    rows = list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
    assert len(rows) == 2
    for value in rows[1]:
        assert not value.lstrip().startswith(("=", "+", "-", "@")), value
