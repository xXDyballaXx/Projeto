from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import ApiCredential, Consent, Integration, User
from app.routes import integrations as integrations_route
from app.services.integration_credentials import load_company_integration


def registration_payload(email: str, company: str) -> dict:
    return {
        "name": "Pessoa Teste",
        "company_name": company,
        "email": email,
        "password": "Senha123",
        "password_confirmation": "Senha123",
        "accept_terms": True,
    }


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_contact(client, phone: str, *, headers: dict[str, str] | None = None, **overrides) -> dict:
    payload = {
        "name": "Contato Teste",
        "phone": phone,
        "email": None,
        "tags": [],
        "source": "manual",
        "consents": [],
    }
    payload.update(overrides)
    response = client.post("/api/contacts", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_integration_credentials_are_encrypted_masked_simulated_and_removed(auth):
    client = auth["client"]
    secret = "sk-company-secret-123456"

    saved = client.post(
        "/api/integrations",
        json={"provider": "ai", "credentials": {"api_key": secret}},
    )

    assert saved.status_code == 201, saved.text
    integration_id = saved.json()["id"]
    with SessionLocal() as db:
        integration = db.get(Integration, integration_id)
        credential = db.scalar(
            select(ApiCredential).where(ApiCredential.integration_id == integration_id)
        )
        assert integration is not None
        assert integration.is_active is False
        assert credential is not None
        assert credential.encrypted_value != secret
        assert secret not in credential.encrypted_value
        assert credential.masked_hint.endswith(secret[-4:])
        credential_id = credential.id

    listed = client.get("/api/integrations")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == integration_id
    assert listed.json()[0]["credential_hints"][0].endswith(secret[-4:])
    assert secret not in listed.text

    simulated = client.post(f"/api/integrations/{integration_id}/test")
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["connected"] is False
    assert simulated.json()["simulation"] is True
    with SessionLocal() as db:
        integration = db.get(Integration, integration_id)
        assert integration is not None
        assert integration.is_active is False
        assert integration.last_tested_at is not None

    removed = client.delete(f"/api/integrations/{integration_id}")
    assert removed.status_code == 204, removed.text
    with SessionLocal() as db:
        assert db.get(Integration, integration_id) is None
        assert db.get(ApiCredential, credential_id) is None


def test_real_integration_test_uses_saved_company_credential(auth, monkeypatch):
    client = auth["client"]
    secret = "sk-official-api-987654"
    saved = client.post(
        "/api/integrations",
        json={"provider": "ai", "credentials": {"api_key": secret}},
    )
    assert saved.status_code == 201, saved.text
    integration_id = saved.json()["id"]

    class ConfirmedResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": settings.ai_model}

    class RecordingAsyncClient:
        calls: list[dict] = []

        def __init__(self, *, timeout):
            assert timeout == 15

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, *, params, headers):
            self.calls.append({"url": url, "params": params, "headers": headers})
            return ConfirmedResponse()

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "external_services_enabled", True)
    monkeypatch.setattr(integrations_route.httpx, "AsyncClient", RecordingAsyncClient)

    tested = client.post(f"/api/integrations/{integration_id}/test")

    assert tested.status_code == 200, tested.text
    assert tested.json()["connected"] is True
    assert tested.json()["simulation"] is False
    assert len(RecordingAsyncClient.calls) == 1
    assert RecordingAsyncClient.calls[0]["url"].endswith(f"/models/{settings.ai_model}")
    assert RecordingAsyncClient.calls[0]["headers"] == {"Authorization": f"Bearer {secret}"}
    with SessionLocal() as db:
        integration = db.get(Integration, integration_id)
        assert integration is not None
        assert integration.is_active is True
        assert integration.last_error is None


def test_integration_credentials_and_operations_are_isolated_by_company(auth):
    client = auth["client"]
    token_a = auth["token"]
    registered_b = client.post(
        "/api/auth/register",
        json=registration_payload("tenant-b@example.com", "Empresa B"),
    )
    assert registered_b.status_code == 201, registered_b.text
    token_b = registered_b.json()["access_token"]
    headers_a, headers_b = bearer(token_a), bearer(token_b)

    saved_a = client.post(
        "/api/integrations",
        json={"provider": "ai", "credentials": {"api_key": "secret-tenant-a"}},
        headers=headers_a,
    )
    saved_b = client.post(
        "/api/integrations",
        json={"provider": "ai", "credentials": {"api_key": "secret-tenant-b"}},
        headers=headers_b,
    )
    assert saved_a.status_code == 201, saved_a.text
    assert saved_b.status_code == 201, saved_b.text
    integration_a = saved_a.json()["id"]
    integration_b = saved_b.json()["id"]
    assert integration_a != integration_b

    with SessionLocal() as db:
        user_a = db.scalar(select(User).where(User.email == "ana@example.com"))
        user_b = db.scalar(select(User).where(User.email == "tenant-b@example.com"))
        assert user_a is not None and user_b is not None
        resolved_a = load_company_integration(db, user_a.company_id, "ai")
        resolved_b = load_company_integration(db, user_b.company_id, "ai")
        assert resolved_a.credentials == {"api_key": "secret-tenant-a"}
        assert resolved_b.credentials == {"api_key": "secret-tenant-b"}
        assert resolved_a.integration.id == integration_a
        assert resolved_b.integration.id == integration_b

    assert [item["id"] for item in client.get("/api/integrations", headers=headers_a).json()] == [integration_a]
    assert [item["id"] for item in client.get("/api/integrations", headers=headers_b).json()] == [integration_b]
    assert client.post(f"/api/integrations/{integration_a}/test", headers=headers_b).status_code == 404
    assert client.delete(f"/api/integrations/{integration_a}", headers=headers_b).status_code == 404
    assert client.get("/api/integrations", headers=headers_a).json()[0]["id"] == integration_a


def test_contact_update_normalizes_fields_and_preserves_state_on_duplicate_phone(auth):
    client = auth["client"]
    first = create_contact(client, "+55 (11) 98888-0001", name="Primeiro")
    second = create_contact(client, "+55 (11) 98888-0002", name="Segundo")

    updated = client.patch(
        f"/api/contacts/{first['id']}",
        json={
            "name": "Primeiro Atualizado",
            "phone": "+55 (11) 97777-0011",
            "tags": [" cliente ", "vip", "cliente"],
            "source": "evento",
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Primeiro Atualizado"
    assert updated.json()["phone"] == "+5511977770011"
    assert updated.json()["tags"] == ["cliente", "vip"]
    assert updated.json()["source"] == "evento"

    duplicate = client.patch(
        f"/api/contacts/{second['id']}",
        json={"phone": "55 11 97777 0011", "name": "Nao deve persistir"},
    )
    assert duplicate.status_code == 409, duplicate.text

    contacts = client.get("/api/contacts").json()
    unchanged = next(item for item in contacts if item["id"] == second["id"])
    assert unchanged["name"] == "Segundo"
    assert unchanged["phone"] == "+5511988880002"


def test_permanent_contact_block_revokes_consent_and_cannot_be_reversed(auth):
    client = auth["client"]
    contact = create_contact(
        client,
        "+55 (11) 98888-0020",
        name="Titular com consentimento",
        consents=[
            {
                "channel": "whatsapp",
                "is_granted": True,
                "source": "formulario",
                "proof": "checkbox registrado",
            }
        ],
    )

    blocked = client.patch(
        f"/api/contacts/{contact['id']}",
        json={"permanently_blocked": True},
    )

    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["permanently_blocked"] is True
    assert blocked.json()["is_active"] is False
    assert blocked.json()["consents"][0]["is_granted"] is False
    assert blocked.json()["consents"][0]["revoked_at"] is not None
    assert client.patch(
        f"/api/contacts/{contact['id']}", json={"permanently_blocked": False}
    ).status_code == 409
    assert client.patch(
        f"/api/contacts/{contact['id']}", json={"is_active": True}
    ).status_code == 409
    assert client.post(
        f"/api/contacts/{contact['id']}/consents",
        json={"channel": "whatsapp", "is_granted": True, "source": "manual"},
    ).status_code == 409
    with SessionLocal() as db:
        consent = db.scalar(select(Consent).where(Consent.contact_id == contact["id"]))
        assert consent is not None
        assert consent.is_granted is False
        assert consent.revoked_at is not None


def test_contact_list_crud_membership_idempotency_and_tenant_isolation(auth):
    client = auth["client"]
    token_a = auth["token"]
    headers_a = bearer(token_a)
    first = create_contact(client, "+55 (11) 98888-0031", headers=headers_a, name="Contato A1")
    second = create_contact(client, "+55 (11) 98888-0032", headers=headers_a, name="Contato A2")

    created = client.post(
        "/api/contacts/lists",
        json={"name": "Clientes VIP", "description": "Lista inicial", "contact_ids": [first["id"]]},
        headers=headers_a,
    )
    assert created.status_code == 201, created.text
    list_id = created.json()["id"]
    assert created.json()["contacts"] == 1

    listed = client.get("/api/contacts/lists/all", headers=headers_a)
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {"id": list_id, "name": "Clientes VIP", "description": "Lista inicial", "contacts": 1}
    ]
    details = client.get(f"/api/contacts/lists/{list_id}", headers=headers_a)
    assert details.status_code == 200, details.text
    assert details.json()["contact_ids"] == [first["id"]]

    updated = client.patch(
        f"/api/contacts/lists/{list_id}",
        json={"name": "Clientes Prioritarios", "description": "Revisada", "contact_ids": [second["id"]]},
        headers=headers_a,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Clientes Prioritarios"
    assert updated.json()["contact_ids"] == [second["id"]]

    added = client.post(
        f"/api/contacts/lists/{list_id}/contacts/{first['id']}", headers=headers_a
    )
    added_again = client.post(
        f"/api/contacts/lists/{list_id}/contacts/{first['id']}", headers=headers_a
    )
    assert added.status_code == 200 and added.json()["contacts"] == 2
    assert added_again.status_code == 200 and added_again.json()["contacts"] == 2

    removed = client.delete(
        f"/api/contacts/lists/{list_id}/contacts/{second['id']}", headers=headers_a
    )
    removed_again = client.delete(
        f"/api/contacts/lists/{list_id}/contacts/{second['id']}", headers=headers_a
    )
    assert removed.status_code == 200 and removed.json()["contacts"] == 1
    assert removed_again.status_code == 200 and removed_again.json()["contacts"] == 1

    registered_b = client.post(
        "/api/auth/register",
        json=registration_payload("list-tenant-b@example.com", "Empresa Lista B"),
    )
    assert registered_b.status_code == 201, registered_b.text
    headers_b = bearer(registered_b.json()["access_token"])
    foreign_contact = create_contact(
        client, "+55 (11) 98888-0040", headers=headers_b, name="Contato B"
    )
    foreign_list = client.post(
        "/api/contacts/lists",
        json={"name": "Lista B", "contact_ids": [foreign_contact["id"]]},
        headers=headers_b,
    )
    assert foreign_list.status_code == 201, foreign_list.text
    assert client.get(
        f"/api/contacts/lists/{foreign_list.json()['id']}", headers=headers_a
    ).status_code == 404
    assert client.post(
        f"/api/contacts/lists/{list_id}/contacts/{foreign_contact['id']}", headers=headers_a
    ).status_code == 404

    deleted = client.delete(f"/api/contacts/lists/{list_id}", headers=headers_a)
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/contacts/lists/{list_id}", headers=headers_a).status_code == 404
