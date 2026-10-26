def test_login_wrong_password(client):
    res = client.post("/auth/login", data={"username": "admin", "password": "sai"})
    assert res.status_code == 400


def test_me_returns_role(client, admin_headers):
    res = client.get("/auth/me", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_protected_endpoint_requires_token(client):
    assert client.get("/api/sdn/topology").status_code == 401


def test_invalid_token_rejected(client):
    res = client.get("/api/sdn/topology", headers={"Authorization": "Bearer abc.def.ghi"})
    assert res.status_code == 401


def test_no_public_registration(client):
    """Không có đăng ký công khai: endpoint /auth/register đã bị gỡ"""
    res = client.post("/auth/register", json={"username": "newuser", "password": "secret123"})
    assert res.status_code in (404, 405)


def test_anonymous_cannot_create_user(client):
    res = client.post("/api/users", json={"username": "newuser", "password": "secret123"})
    assert res.status_code == 401


def test_viewer_cannot_create_user(client, viewer_headers):
    res = client.post("/api/users", headers=viewer_headers, json={"username": "newuser", "password": "secret123"})
    assert res.status_code == 403
    assert client.post("/auth/login", data={"username": "newuser", "password": "secret123"}).status_code == 400


def test_admin_creates_viewer_and_admin(client, admin_headers):
    for name, role in (("viewer2", "viewer"), ("admin2", "admin")):
        res = client.post("/api/users", headers=admin_headers, json={"username": name, "password": "secret123", "role": role})
        assert res.status_code == 200 and res.json()["role"] == role
        assert client.post("/auth/login", data={"username": name, "password": "secret123"}).status_code == 200


def test_create_user_duplicate_username(client, admin_headers):
    res = client.post("/api/users", headers=admin_headers, json={"username": "admin", "password": "secret123"})
    assert res.status_code == 400
