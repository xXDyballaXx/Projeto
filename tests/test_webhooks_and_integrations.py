import asyncio

from app.services.whatsapp_service import whatsapp_service


def test_webhook_verification_rejects_unknown_token(client):
    assert client.get("/webhooks/meta?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123").status_code == 403


def test_signed_webhook_simulation_accepts_payload(client):
    response = client.post("/webhooks/meta", json={"entry": []})
    assert response.status_code == 200
    assert response.json()["received"] is True


def test_unsubscribe_message_revokes_whatsapp_consent(auth):
    client = auth["client"]
    created = client.post("/api/contacts", json={"name": "Opt-in", "phone": "+5511999990000", "source": "site", "consents": [{"channel": "whatsapp", "source": "site", "is_granted": True}]}).json()
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "5511999990000", "text": {"body": "SAIR"}}]}}]}]}
    response = client.post("/webhooks/meta", json=payload)
    assert response.status_code == 200
    contact = next(item for item in client.get("/api/contacts").json() if item["id"] == created["id"])
    assert contact["consents"][0]["is_granted"] is False


def test_external_api_is_clearly_simulated_without_credentials():
    result = asyncio.run(whatsapp_service.send_template("+5511999999999", "template_aprovado"))
    assert result.simulated is True
    assert result.success is False
    assert "SIMULAÇÃO" in result.error
