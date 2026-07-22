import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_divulgai.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-with-enough-entropy"
os.environ["SECRET_KEY"] = "test-secret-with-enough-entropy"

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

