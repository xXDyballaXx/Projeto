import os

os.environ["DATABASE_URL"] = "sqlite:///./test_divulgai.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "false"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["EXTERNAL_SERVICES_ENABLED"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-with-enough-entropy"
os.environ["SECRET_KEY"] = "test-secret-with-enough-entropy"
for credential_name in (
    "META_APP_ID",
    "META_APP_SECRET",
    "META_VERIFY_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_BUSINESS_ACCOUNT_ID",
    "WHATSAPP_ACCESS_TOKEN",
    "FACEBOOK_PAGE_ID",
    "FACEBOOK_PAGE_ACCESS_TOKEN",
    "INSTAGRAM_ACCOUNT_ID",
    "AI_API_KEY",
):
    os.environ.pop(credential_name, None)

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(client):
    payload = {"name": "Ana", "company_name": "Empresa Teste", "email": "ana@example.com", "password": "Senha123", "password_confirmation": "Senha123", "accept_terms": True}
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201
    return {"client": client, "token": response.json()["access_token"]}

