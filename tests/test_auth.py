def test_register_and_login(client):
    registration = {"name": "João", "company_name": "Acme", "email": "joao@example.com", "password": "Segura123", "password_confirmation": "Segura123", "accept_terms": True}
    assert client.post("/api/auth/register", json=registration).status_code == 201
    login = client.post("/api/auth/login", json={"email": "joao@example.com", "password": "Segura123"})
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"


def test_registration_validations(client):
    payload = {"name": "A", "company_name": "X", "email": "bad", "password": "short", "password_confirmation": "other", "accept_terms": False}
    assert client.post("/api/auth/register", json=payload).status_code == 422


def test_login_brute_force_lock(client, auth):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "errada"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "Senha123"}).status_code == 429

