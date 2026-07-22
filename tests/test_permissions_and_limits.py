def test_admin_route_rejects_regular_user(auth):
    assert auth["client"].get("/api/admin/overview").status_code == 403


def test_unauthenticated_api_is_rejected(client):
    assert client.get("/api/contacts").status_code == 401

