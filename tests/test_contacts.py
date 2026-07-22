import io


def test_contact_requires_explicit_consent(auth):
    client = auth["client"]
    response = client.post("/api/contacts", json={"name": "Cliente", "phone": "+5511999999999", "source": "formulário", "consents": []})
    assert response.status_code == 201
    assert response.json()["consents"] == []


def test_create_and_revoke_consent(auth):
    client = auth["client"]
    created = client.post("/api/contacts", json={"name": "Maria", "phone": "+5511988887777", "source": "checkout", "consents": [{"channel": "whatsapp", "source": "checkbox checkout", "is_granted": True}]}).json()
    assert created["consents"][0]["is_granted"] is True
    revoked = client.post(f"/api/contacts/{created['id']}/consents", json={"channel": "whatsapp", "source": "solicitação", "is_granted": False}).json()
    assert revoked["consents"][0]["is_granted"] is False


def test_csv_import_only_records_declared_consent(auth):
    csv_data = "nome,telefone,email,consentimento,canal,origem\nCom Optin,+5511911111111,,sim,whatsapp,evento\nSem Optin,+5511922222222,,não,whatsapp,lista\n"
    result = auth["client"].post("/api/contacts/import/csv", files={"file": ("contatos.csv", csv_data.encode(), "text/csv")})
    assert result.status_code == 200
    contacts = auth["client"].get("/api/contacts").json()
    assert len(contacts) == 2
    assert sum(bool(item["consents"]) for item in contacts) == 1


def test_create_and_list_contact_group(auth):
    client = auth["client"]
    first = client.post("/api/contacts", json={"name": "Contato Um", "phone": "+5511900000001", "source": "manual"}).json()
    second = client.post("/api/contacts", json={"name": "Contato Dois", "phone": "+5511900000002", "source": "manual"}).json()
    created = client.post("/api/contacts/lists", json={"name": "Clientes ativos", "description": "Lista de teste", "contact_ids": [first["id"], second["id"]]})
    assert created.status_code == 201
    assert created.json()["contacts"] == 2
    lists = client.get("/api/contacts/lists/all").json()
    assert lists == [{"id": created.json()["id"], "name": "Clientes ativos", "description": "Lista de teste", "contacts": 2}]
