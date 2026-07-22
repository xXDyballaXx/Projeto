from app.services.tracking_service import make_tracking_url


def test_signed_click_is_recorded(auth):
    client = auth["client"]
    campaign = client.post("/api/campaigns", json={"internal_name": "Clique", "title": "Oferta", "body": "Conheça", "channel": "facebook", "link_url": "https://example.com/oferta"}).json()
    path = make_tracking_url(campaign["id"]).replace("http://localhost:8000", "")
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/oferta"
    assert client.get("/api/dashboard").json()["totals"]["clicks"] == 1

