import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import Settings, settings
from app.database import SessionLocal
from app.models import Role, User


def registration_payload(email: str = "nova@example.com") -> dict:
    return {
        "name": "Nova Pessoa",
        "company_name": "Nova Empresa",
        "email": email,
        "password": "Senha123",
        "password_confirmation": "Senha123",
        "accept_terms": True,
    }


def cookie_value(client, name: str) -> str | None:
    return next((cookie.value for cookie in client.cookies.jar if cookie.name == name), None)


def valid_production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "debug": False,
        "secret_key": "s" * 48,
        "jwt_secret_key": "j" * 48,
        "encryption_key": Fernet.generate_key().decode(),
        "allowed_origins": "https://app.example.com",
        "base_url": "https://app.example.com",
        "database_url": "postgresql+psycopg://app:strong-password@db:5432/divulgai",
    }
    values.update(overrides)
    return Settings(**values)


def test_admin_email_does_not_promote_public_registration(client, monkeypatch):
    email = "bootstrap-admin@example.com"
    monkeypatch.setattr(settings, "admin_email", email)

    response = client.post("/api/auth/register", json=registration_payload(email))

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.role == Role.user
    assert client.get("/api/admin/overview").status_code == 403


def test_refresh_rotates_cookie_and_logout_removes_session_cookies(client):
    registration = client.post("/api/auth/register", json=registration_payload())

    assert registration.status_code == 201, registration.text
    set_cookie = registration.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/api/auth" in set_cookie

    original_access = cookie_value(client, "access_token")
    original_refresh = cookie_value(client, "refresh_token")
    assert original_access
    assert original_refresh

    client.cookies.delete("access_token")
    assert client.get("/api/settings/profile").status_code == 401

    refreshed = client.post("/api/auth/refresh")

    assert refreshed.status_code == 200, refreshed.text
    assert cookie_value(client, "access_token") not in {None, original_access}
    assert cookie_value(client, "refresh_token") not in {None, original_refresh}
    assert client.get("/api/settings/profile").status_code == 200

    logout = client.post("/api/auth/logout")

    assert logout.status_code == 200, logout.text
    assert cookie_value(client, "access_token") is None
    assert cookie_value(client, "refresh_token") is None
    assert client.get("/api/settings/profile").status_code == 401


def test_refresh_rejects_access_token_as_refresh_token(client):
    registration = client.post("/api/auth/register", json=registration_payload())
    assert registration.status_code == 201, registration.text

    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": registration.json()["access_token"]},
    )

    assert response.status_code == 401
    assert response.json()["detail"].startswith("Tipo de token")


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_key": ""},
        {"jwt_secret_key": ""},
        {"secret_key": "curta"},
        {"jwt_secret_key": "curta"},
        {"secret_key": "x" * 48, "jwt_secret_key": "x" * 48},
        {"encryption_key": ""},
        {"encryption_key": "nao-e-uma-chave-fernet"},
        {"allowed_origins": ""},
        {"allowed_origins": "*"},
        {"allowed_origins": "http://app.example.com"},
        {"base_url": "http://app.example.com"},
        {"database_url": "sqlite:///./production.db"},
        {"database_url": "postgresql+psycopg://divulgai:divulgai@db:5432/divulgai"},
        {"debug": True},
    ],
)
def test_production_rejects_insecure_configuration(overrides):
    candidate = valid_production_settings(**overrides)

    with pytest.raises(RuntimeError):
        candidate.assert_production_secrets()


def test_production_accepts_valid_distinct_secrets():
    valid_production_settings().assert_production_secrets()


def test_profile_get_and_update_persist_user_and_company_settings(auth):
    client = auth["client"]
    initial = client.get("/api/settings/profile")

    assert initial.status_code == 200, initial.text
    assert initial.json()["name"] == "Ana"
    assert initial.json()["email"] == "ana@example.com"
    assert initial.json()["company"] == "Empresa Teste"

    update = client.patch(
        "/api/settings/profile",
        json={
            "name": "Ana Atualizada",
            "company": "Empresa Atualizada",
            "email": "ana.nova@example.com",
            "timezone": "America/Manaus",
            "daily_limit": 321,
            "unsubscribe_policy": "Cancelar imediatamente em todos os canais.",
            "sending_preferences": {"quiet_hours": True, "start": "20:00"},
        },
    )

    assert update.status_code == 200, update.text
    saved = client.get("/api/settings/profile")
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "name": "Ana Atualizada",
        "email": "ana.nova@example.com",
        "company": "Empresa Atualizada",
        "timezone": "America/Manaus",
        "daily_limit": 321,
        "unsubscribe_policy": "Cancelar imediatamente em todos os canais.",
        "sending_preferences": {"quiet_hours": True, "start": "20:00"},
        "role": "user",
    }


def test_profile_update_rejects_invalid_timezone(auth):
    response = auth["client"].patch(
        "/api/settings/profile",
        json={"timezone": "Fuso/Inexistente"},
    )

    assert response.status_code == 422
    assert any(error["loc"][-1] == "timezone" for error in response.json()["detail"])


def test_password_update_validates_current_password_and_changes_login(auth):
    client = auth["client"]

    wrong_current = client.post(
        "/api/settings/password",
        json={"current_password": "SenhaErrada123", "new_password": "NovaSenha456"},
    )
    weak_new = client.post(
        "/api/settings/password",
        json={"current_password": "Senha123", "new_password": "apenasletras"},
    )
    changed = client.post(
        "/api/settings/password",
        json={"current_password": "Senha123", "new_password": "NovaSenha456"},
    )

    assert wrong_current.status_code == 400
    assert weak_new.status_code == 400
    assert changed.status_code == 200, changed.text
    assert client.post(
        "/api/auth/login",
        json={"email": "ana@example.com", "password": "Senha123"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "ana@example.com", "password": "NovaSenha456"},
    ).status_code == 200
