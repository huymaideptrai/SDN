def test_change_password(client, viewer_headers):
    res = client.post("/auth/change-password", headers=viewer_headers,
                      json={"current_password": "viewer123", "new_password": "newpass456"})
    assert res.status_code == 200
    assert client.post("/auth/login", data={"username": "viewer", "password": "viewer123"}).status_code == 400
    assert client.post("/auth/login", data={"username": "viewer", "password": "newpass456"}).status_code == 200


def test_change_password_wrong_current(client, viewer_headers):
    res = client.post("/auth/change-password", headers=viewer_headers,
                      json={"current_password": "sai-mat-khau", "new_password": "newpass456"})
    assert res.status_code == 400


def test_change_password_must_differ(client, viewer_headers):
    res = client.post("/auth/change-password", headers=viewer_headers,
                      json={"current_password": "viewer123", "new_password": "viewer123"})
    assert res.status_code == 422


def test_viewer_cannot_manage_users(client, viewer_headers):
    assert client.get("/api/users", headers=viewer_headers).status_code == 403
    assert client.get("/api/audit-logs", headers=viewer_headers).status_code == 403


def test_admin_creates_and_updates_user(client, admin_headers):
    res = client.post("/api/users", headers=admin_headers,
                      json={"username": "operator", "password": "secret123", "role": "viewer"})
    assert res.status_code == 200
    uid = res.json()["id"]

    res = client.patch(f"/api/users/{uid}", headers=admin_headers, json={"role": "admin"})
    assert res.status_code == 200 and res.json()["role"] == "admin"

    res = client.patch(f"/api/users/{uid}", headers=admin_headers, json={"is_active": False})
    assert res.status_code == 200 and res.json()["is_active"] is False
    # Tài khoản bị khoá không đăng nhập được
    assert client.post("/auth/login", data={"username": "operator", "password": "secret123"}).status_code == 403


def test_locked_user_token_rejected_immediately(client, admin_headers, viewer_headers):
    users = client.get("/api/users", headers=admin_headers).json()
    viewer_id = next(u["id"] for u in users if u["username"] == "viewer")
    client.patch(f"/api/users/{viewer_id}", headers=admin_headers, json={"is_active": False})
    assert client.get("/auth/me", headers=viewer_headers).status_code == 401


def test_admin_cannot_lock_or_demote_self(client, admin_headers):
    me = client.get("/auth/me", headers=admin_headers).json()
    assert client.patch(f"/api/users/{me['id']}", headers=admin_headers, json={"is_active": False}).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", headers=admin_headers, json={"role": "viewer"}).status_code == 400


def test_admin_can_demote_another_admin(client, admin_headers):
    res = client.post("/api/users", headers=admin_headers, json={"username": "admin2", "password": "secret123", "role": "admin"})
    uid = res.json()["id"]
    res = client.patch(f"/api/users/{uid}", headers=admin_headers, json={"role": "viewer"})
    assert res.status_code == 200 and res.json()["role"] == "viewer"
    # Quyền thay đổi có hiệu lực ngay với token đã cấp (role đọc lại từ DB)
    h2 = {"Authorization": "Bearer " + client.post("/auth/login", data={"username": "admin2", "password": "secret123"}).json()["access_token"]}
    assert client.get("/api/users", headers=h2).status_code == 403


def test_reset_password_and_audit_log(client, admin_headers):
    users = client.get("/api/users", headers=admin_headers).json()
    viewer_id = next(u["id"] for u in users if u["username"] == "viewer")
    assert client.post(f"/api/users/{viewer_id}/reset-password", headers=admin_headers,
                       json={"new_password": "reset789"}).status_code == 200
    assert client.post("/auth/login", data={"username": "viewer", "password": "reset789"}).status_code == 200

    logs = client.get("/api/audit-logs", headers=admin_headers).json()
    assert logs[0]["action"] == "RESET_PASSWORD" and logs[0]["username"] == "admin" and logs[0]["dpid"] == "-"
