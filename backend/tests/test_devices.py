import pytest
from app.main import app
from app.services.snmp_client import SnmpError, get_snmp_collector, health_cache


class FakeCollector:
    """Mô phỏng thiết bị SNMP theo host: 'ok-host' trả số liệu, còn lại không phản hồi"""

    def __init__(self):
        self.calls = []

    async def collect(self, cfg):
        self.calls.append((cfg.host, cfg.version, cfg.community, cfg.v3_user))
        if cfg.host != "ok-host":
            raise SnmpError("No SNMP response received before timeout")
        return {"sys_descr": "Test switch", "sys_name": "sw-test", "uptime_s": 3600,
                "cpu": {"percent": 12.5, "cores": 2, "source": "HOST-RESOURCES-MIB"},
                "memory": {"name": "RAM", "total": 4096, "used": 1024, "source": "HOST-RESOURCES-MIB"},
                "storage": [], "temperatures": [{"name": "CPU", "celsius": 41.5, "source": "ENTITY-SENSOR-MIB"}]}


@pytest.fixture
def collector(client):
    fake = FakeCollector()
    app.dependency_overrides[get_snmp_collector] = lambda: fake
    health_cache._data.clear()
    yield fake
    app.dependency_overrides.pop(get_snmp_collector, None)
    health_cache._data.clear()


def test_switch_without_snmp_is_not_configured(client, viewer_headers, collector):
    devices = client.get("/api/devices/health", headers=viewer_headers).json()["devices"]
    assert [(d["dpid"], d["status"]) for d in devices] == [(1, "not_configured"), (2, "not_configured")]
    # Không có số liệu nào được bịa ra cho switch chưa cấu hình
    assert all("cpu" not in d for d in devices)
    assert collector.calls == []


def test_health_reads_from_device(client, admin_headers, viewer_headers, collector):
    assert client.put("/api/devices/snmp/1", headers=admin_headers,
                      json={"host": "ok-host", "community": "public"}).status_code == 200
    assert client.put("/api/devices/snmp/2", headers=admin_headers,
                      json={"host": "dead-host", "community": "public"}).status_code == 200
    devices = {d["dpid"]: d for d in client.get("/api/devices/health", headers=viewer_headers).json()["devices"]}
    assert devices[1]["status"] == "ok" and devices[1]["cpu"]["percent"] == 12.5 and devices[1]["temperatures"][0]["celsius"] == 41.5
    assert devices[2]["status"] == "unreachable" and "timeout" in devices[2]["error"]
    assert "cpu" not in devices[2]


def test_health_is_cached(client, admin_headers, viewer_headers, collector):
    client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "community": "public"})
    for _ in range(3):
        client.get("/api/devices/health", headers=viewer_headers)
    assert len(collector.calls) == 1


def test_secrets_never_returned(client, admin_headers, collector):
    client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "community": "s3cr3t-community"})
    client.put("/api/devices/snmp/2", headers=admin_headers, json={
        "host": "ok-host", "version": "3", "v3_user": "monitor", "v3_auth_proto": "SHA", "v3_auth_key": "authkey-123",
        "v3_priv_proto": "AES", "v3_priv_key": "privkey-123"})
    raw = client.get("/api/devices/snmp", headers=admin_headers).text
    for secret in ("s3cr3t-community", "authkey-123", "privkey-123"):
        assert secret not in raw
    cfgs = {c["dpid"]: c for c in client.get("/api/devices/snmp", headers=admin_headers).json()}
    assert cfgs[1]["has_community"] and cfgs[2]["has_auth_key"] and cfgs[2]["has_priv_key"] and cfgs[2]["v3_user"] == "monitor"


def test_update_keeps_secret_when_blank(client, admin_headers, collector):
    client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "community": "first"})
    # Sửa host, bỏ trống community -> giữ community cũ
    res = client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "port": 1161, "community": ""})
    assert res.status_code == 200 and res.json()["port"] == 1161
    client.post("/api/devices/snmp/1/test", headers=admin_headers)
    assert collector.calls[-1][2] == "first"


def test_validation(client, admin_headers, collector):
    assert client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host"}).status_code == 422  # v2c thiếu community
    assert client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "version": "3"}).status_code == 422
    assert client.put("/api/devices/snmp/1", headers=admin_headers, json={
        "host": "ok-host", "version": "3", "v3_user": "u", "v3_auth_proto": "SHA", "v3_auth_key": "short"}).status_code == 422
    assert client.put("/api/devices/snmp/1", headers=admin_headers, json={
        "host": "ok-host", "version": "3", "v3_user": "u", "v3_priv_proto": "AES", "v3_priv_key": "privkey-123"}).status_code == 422


def test_viewer_cannot_manage_snmp(client, viewer_headers, collector):
    assert client.get("/api/devices/snmp", headers=viewer_headers).status_code == 403
    assert client.put("/api/devices/snmp/1", headers=viewer_headers, json={"host": "ok-host", "community": "p"}).status_code == 403
    assert client.post("/api/devices/snmp/1/test", headers=viewer_headers).status_code == 403
    assert client.get("/api/devices/health").status_code == 401


def test_test_and_delete(client, admin_headers, collector):
    assert client.post("/api/devices/snmp/1/test", headers=admin_headers).status_code == 404
    client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "community": "public"})
    res = client.post("/api/devices/snmp/1/test", headers=admin_headers).json()
    assert res["status"] == "ok" and res["sys_name"] == "sw-test"
    assert client.delete("/api/devices/snmp/1", headers=admin_headers).status_code == 200
    devices = client.get("/api/devices/health", headers=admin_headers).json()["devices"]
    assert devices[0]["status"] == "not_configured"
    logs = [l["action"] for l in client.get("/api/audit-logs", headers=admin_headers).json()]
    assert "SET_SNMP" in logs and "DELETE_SNMP" in logs



def test_stale_result_served_while_refreshing(client, admin_headers, viewer_headers, collector, monkeypatch):
    """Hết hạn cache: trả ngay kết quả cũ (stale) và đọc lại ở nền, không bắt người xem chờ timeout SNMP"""
    import time as _time
    client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "community": "public"})
    first = client.get("/api/devices/health", headers=viewer_headers).json()["devices"][0]
    assert first["status"] == "ok" and first["stale"] is False
    monkeypatch.setattr(health_cache, "ttl", 0.01)
    _time.sleep(0.05)
    second = client.get("/api/devices/health", headers=viewer_headers).json()["devices"][0]
    assert second["status"] == "ok" and second["stale"] is True
    assert second["collected_at"] == first["collected_at"]


def test_test_button_bypasses_cache(client, admin_headers, collector):
    client.put("/api/devices/snmp/1", headers=admin_headers, json={"host": "ok-host", "community": "public"})
    client.get("/api/devices/health", headers=admin_headers)
    n = len(collector.calls)
    client.post("/api/devices/snmp/1/test", headers=admin_headers)
    assert len(collector.calls) == n + 1
