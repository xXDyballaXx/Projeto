from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import Campaign, CampaignRecipient, CampaignStatus, Channel, Consent, Contact, MessageTemplate
from app.services.campaign_service import materialize_recipients


def test_create_campaign(auth):
    response = auth["client"].post("/api/campaigns", json={"internal_name": "Lançamento", "title": "Novidade", "body": "Conheça nossa novidade", "channel": "facebook", "timezone": "America/Sao_Paulo"})
    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_edit_and_delete_campaign(auth):
    client = auth["client"]
    campaign = client.post("/api/campaigns", json={"internal_name": "Original", "title": "Título original", "body": "Texto original", "channel": "facebook"}).json()
    edited = client.patch(f"/api/campaigns/{campaign['id']}", json={"internal_name": "Campanha editada", "title": "Novo título", "body": "Novo texto", "channel": "instagram"})
    assert edited.status_code == 200
    assert edited.json()["internal_name"] == "Campanha editada"
    assert edited.json()["channel"] == "instagram"
    deleted = client.delete(f"/api/campaigns/{campaign['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/campaigns").json() == []


def test_send_uses_local_eager_mode_without_redis(auth):
    client = auth["client"]
    campaign = client.post("/api/campaigns", json={"internal_name": "Envio local", "title": "Teste", "body": "Conteúdo de teste", "channel": "facebook"}).json()
    response = client.post(f"/api/campaigns/{campaign['id']}/send")
    assert response.status_code == 200
    assert response.json()["message"] == "Campanha processada no modo local."
    assert response.json()["result"]["status"] == "simulation"


def test_whatsapp_creation_requires_ready_list(auth):
    client = auth["client"]
    missing_list = client.post("/api/campaigns", json={"internal_name": "WhatsApp inválida", "title": "Teste", "body": "Mensagem", "channel": "whatsapp"})
    assert missing_list.status_code == 422
    assert "Selecione uma lista" in missing_list.json()["detail"]


def test_whatsapp_ready_campaign_finishes_as_simulated_locally(auth):
    client = auth["client"]
    contact = client.post("/api/contacts", json={"name": "Contato autorizado", "phone": "+5511900000099", "source": "formulário", "consents": [{"channel": "whatsapp", "source": "formulário", "is_granted": True}]}).json()
    contact_list = client.post("/api/contacts/lists", json={"name": "Lista WhatsApp", "contact_ids": [contact["id"]]}).json()
    campaign = client.post("/api/campaigns", json={"internal_name": "Teste WhatsApp", "title": "Oferta", "body": "Mensagem de teste", "channel": "whatsapp", "contact_list_id": contact_list["id"]})
    assert campaign.status_code == 201
    sent = client.post(f"/api/campaigns/{campaign.json()['id']}/send")
    assert sent.status_code == 200
    assert sent.json()["result"]["status"] == "simulated"
    saved = next(item for item in client.get("/api/campaigns").json() if item["id"] == campaign.json()["id"])
    assert saved["status"] == "simulated"


def test_schedule_requires_future_date(auth):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    response = auth["client"].post("/api/campaigns", json={"internal_name": "Agendada", "title": "Olá", "body": "Mensagem", "channel": "facebook", "scheduled_at": future})
    assert response.status_code == 201
    assert response.json()["status"] == "scheduled"


def test_cancel_scheduled_campaign(auth):
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    created = auth["client"].post("/api/campaigns", json={"internal_name": "Cancelar", "title": "Olá", "body": "Mensagem", "channel": "facebook", "scheduled_at": future}).json()
    response = auth["client"].post(f"/api/campaigns/{created['id']}/cancel")
    assert response.status_code == 200
    campaigns = auth["client"].get("/api/campaigns").json()
    assert campaigns[0]["status"] == "cancelled"


def test_recipient_without_consent_is_blocked(auth):
    with SessionLocal() as db:
        from app.models import User, ContactList
        user = db.query(User).first()
        contact = Contact(company_id=user.company_id, name="Sem optin", phone="+5511900000000", source="manual")
        contact_list = ContactList(company_id=user.company_id, name="Lista")
        contact_list.contacts.append(contact)
        db.add_all([contact, contact_list]); db.flush()
        campaign = Campaign(company_id=user.company_id, created_by_id=user.id, contact_list_id=contact_list.id, internal_name="Teste", title="Teste", body="Teste", channel=Channel.whatsapp)
        db.add(campaign); db.commit()
        assert materialize_recipients(db, campaign) == 0
