import asyncio
from app.models.database import SessionLocal
from app.models.models import AuditLog, FlowPolicy, QoSProfile
from app.services import sdn_rules
from app.tasks.sync_worker import sync_once


def add_drop_rule(client, headers, **overrides):
    payload = {"dpid": 1, "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "action": "DROP", "priority": 100}
    payload.update(overrides)
    return client.post("/api/sdn/flows", headers=headers, json=payload)


# ---------- Firewall ----------

def test_add_flow_installs_on_switch_and_saves_db(client, admin_headers, fake_ryu):
    res = add_drop_rule(client, admin_headers)
    assert res.status_code == 200, res.text
    policy_id = res.json()["policy_id"]

    flow = fake_ryu.flows[1][0]
    assert flow["table_id"] == sdn_rules.POLICY_TABLE
    assert flow["cookie"] == sdn_rules.policy_cookie(policy_id)
    assert flow["match"] == {"eth_type": 2048, "ipv4_src": "10.0.0.1", "ipv4_dst": "10.0.0.2"}
    assert flow["actions"] == []

    db = SessionLocal()
    assert db.get(FlowPolicy, policy_id).is_active
    assert db.query(AuditLog).filter(AuditLog.action == "ADD_FLOW_POLICY").count() == 1
    db.close()


def test_allow_rule_goes_to_forward_table(client, admin_headers, fake_ryu):
    """ALLOW không dùng OUTPUT:NORMAL (L2 learning của OVS gây bão broadcast khi topology có vòng)"""
    assert add_drop_rule(client, admin_headers, action="allow").status_code == 200
    assert fake_ryu.flows[1][0]["actions"] == [{"type": "GOTO_TABLE", "table_id": sdn_rules.FORWARD_TABLE}]


def test_viewer_cannot_add_flow(client, viewer_headers, fake_ryu):
    assert add_drop_rule(client, viewer_headers).status_code == 403
    assert fake_ryu.flows[1] == []


def test_invalid_ip_rejected(client, admin_headers):
    assert add_drop_rule(client, admin_headers, src_ip="10.0.0.999").status_code == 422


def test_rule_needs_an_ip(client, admin_headers):
    assert add_drop_rule(client, admin_headers, src_ip=None, dst_ip="").status_code == 422


def test_priority_must_beat_learning_flows(client, admin_headers):
    assert add_drop_rule(client, admin_headers, priority=1).status_code == 422


def test_duplicate_rule_conflict(client, admin_headers):
    assert add_drop_rule(client, admin_headers).status_code == 200
    assert add_drop_rule(client, admin_headers).status_code == 409


def test_ryu_down_does_not_save_policy(client, admin_headers, fake_ryu):
    fake_ryu.down = True
    res = add_drop_rule(client, admin_headers)
    assert res.status_code == 503
    db = SessionLocal()
    assert db.query(FlowPolicy).count() == 0
    db.close()


def test_list_flows_classifies_policy(client, admin_headers, fake_ryu):
    policy_id = add_drop_rule(client, admin_headers).json()["policy_id"]
    fake_ryu.flows[1].append({"cookie": sdn_rules.ROUTE_COOKIE_BASE + 7, "table_id": 2, "priority": 10,
                              "match": {"in_port": 1}, "actions": []})
    fake_ryu.flows[1].append({"cookie": 0, "table_id": 0, "priority": 65535, "match": {"dl_type": 35020}, "actions": []})
    fake_ryu.flows[1].append({"cookie": 0, "table_id": 1, "priority": 0, "match": {}, "actions": []})

    flows = client.get("/api/sdn/flows/1", headers=admin_headers).json()["flows"]
    assert [(f["kind"], f["policy_id"]) for f in flows] == [("system", None), ("policy", policy_id), ("route", None)]


def test_delete_policy_removes_flow_and_deactivates(client, admin_headers, fake_ryu):
    policy_id = add_drop_rule(client, admin_headers).json()["policy_id"]
    res = client.delete(f"/api/sdn/policies/{policy_id}", headers=admin_headers)
    assert res.status_code == 200
    assert fake_ryu.flows[1] == []
    db = SessionLocal()
    assert not db.get(FlowPolicy, policy_id).is_active
    db.close()
    assert client.delete(f"/api/sdn/policies/{policy_id}", headers=admin_headers).status_code == 404


def test_delete_raw_learned_flow(client, admin_headers, fake_ryu):
    fake_ryu.flows[1].append({"cookie": 0, "table_id": 1, "priority": 1, "match": {"in_port": 1}, "actions": []})
    res = client.request("DELETE", "/api/sdn/flows/1", headers=admin_headers,
                         json={"table_id": 1, "priority": 1, "match": {"in_port": 1}})
    assert res.status_code == 200
    assert fake_ryu.flows[1] == []


def test_unknown_switch_returns_404(client, admin_headers):
    assert client.get("/api/sdn/flows/99", headers=admin_headers).status_code == 404


# ---------- QoS ----------

def test_set_qos_creates_meter_and_flow(client, admin_headers, fake_ryu):
    res = client.post("/api/sdn/qos/config", headers=admin_headers, json={"dpid": 1, "port": 2, "max_rate_mbps": 5})
    assert res.status_code == 200, res.text
    assert fake_ryu.meters[1][2]["bands"][0]["rate"] == 5000
    flow = fake_ryu.flows[1][0]
    assert flow["table_id"] == sdn_rules.QOS_TABLE and flow["match"] == {"in_port": 2}

    # Đặt lại -> modify meter, không tạo bản ghi trùng
    res = client.post("/api/sdn/qos/config", headers=admin_headers, json={"dpid": 1, "port": 2, "max_rate_mbps": 10})
    assert res.status_code == 200
    assert fake_ryu.meters[1][2]["bands"][0]["rate"] == 10000
    profiles = client.get("/api/sdn/qos/config/1", headers=admin_headers).json()
    assert [(p["port_no"], p["max_bw"]) for p in profiles] == [(2, 10000)]


def test_qos_rejects_unknown_port(client, admin_headers):
    res = client.post("/api/sdn/qos/config", headers=admin_headers, json={"dpid": 1, "port": 42, "max_rate_mbps": 5})
    assert res.status_code == 400


def test_viewer_cannot_set_qos(client, viewer_headers):
    res = client.post("/api/sdn/qos/config", headers=viewer_headers, json={"dpid": 1, "port": 2, "max_rate_mbps": 5})
    assert res.status_code == 403


def test_delete_qos(client, admin_headers, fake_ryu):
    client.post("/api/sdn/qos/config", headers=admin_headers, json={"dpid": 1, "port": 2, "max_rate_mbps": 5})
    res = client.delete("/api/sdn/qos/config/1/2", headers=admin_headers)
    assert res.status_code == 200
    assert fake_ryu.meters[1] == {} and fake_ryu.flows[1] == []
    db = SessionLocal()
    assert db.query(QoSProfile).count() == 0
    db.close()


def test_qos_stats_skips_local_port(client, admin_headers, monkeypatch):
    from app.routers import sdn
    sdn.last_port_stats.clear()
    monkeypatch.setattr(sdn, "MIN_RATE_WINDOW_S", 0)
    res = client.get("/api/sdn/qos/1", headers=admin_headers)
    assert res.status_code == 200
    stats = res.json()["stats"]
    assert [p["port"] for p in stats] == [1, 2, 3]
    # Lần đầu chưa có mẫu trước -> chưa đo được, lần sau mới có số đo
    assert not any(p["measured"] for p in stats)
    stats = client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"]
    assert all(p["measured"] for p in stats)


# ---------- Sync worker ----------

def test_sync_reinstalls_missing_rules_only(client, admin_headers, fake_ryu):
    add_drop_rule(client, admin_headers)
    client.post("/api/sdn/qos/config", headers=admin_headers, json={"dpid": 1, "port": 2, "max_rate_mbps": 5})

    # Đã đủ -> không cài lại gì (tránh reset bộ đếm)
    assert asyncio.run(sync_once(fake_ryu)) == 0

    # Giả lập switch khởi động lại: mất hết flow và meter
    fake_ryu.flows[1] = []
    fake_ryu.meters[1] = {}
    assert asyncio.run(sync_once(fake_ryu)) == 3
    assert len(fake_ryu.flows[1]) == 2 and 2 in fake_ryu.meters[1]


def test_sync_skips_deleted_policy(client, admin_headers, fake_ryu):
    policy_id = add_drop_rule(client, admin_headers).json()["policy_id"]
    client.delete(f"/api/sdn/policies/{policy_id}", headers=admin_headers)
    assert asyncio.run(sync_once(fake_ryu)) == 0
    assert fake_ryu.flows[1] == []



def test_sync_loop_survives_errors(monkeypatch):
    """Vòng lặp sync phải chạy tiếp sau lỗi, kể cả khi console không in được tiếng Việt
    (stdout bị chuyển hướng ra file trên Windows -> cp1252)"""
    import io
    import sys
    from app.tasks import sync_worker

    calls = []

    async def fake_sync_once():
        calls.append(1)
        if len(calls) == 1:
            return 2  # có cài bù -> ghi log tiếng Việt
        if len(calls) == 2:
            raise RuntimeError("Ryu trả dữ liệu lạ")  # lỗi bất kỳ -> ghi log tiếng Việt
        raise asyncio.CancelledError  # dừng vòng lặp

    for name in ("stdout", "stderr"):
        monkeypatch.setattr(sys, name, io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict"))
    monkeypatch.setattr(sync_worker, "sync_once", fake_sync_once)
    monkeypatch.setattr(sync_worker.settings, "SYNC_INTERVAL_SECONDS", 0)
    try:
        asyncio.run(sync_worker.sync_flow_state())
    except asyncio.CancelledError:
        pass
    assert len(calls) == 3


def test_qos_stats_reports_meter_drops(client, admin_headers, fake_ryu, monkeypatch):
    """Port có QoS: tách lưu lượng đến port và phần bị meter huỷ"""
    import time as _time
    from app.routers import sdn
    monkeypatch.setattr(sdn, "MIN_RATE_WINDOW_S", 0)
    sdn.last_port_stats.clear()
    sdn.last_meter_stats.clear()
    client.post("/api/sdn/qos/config", headers=admin_headers, json={"dpid": 1, "port": 2, "max_rate_mbps": 20})

    fake_ryu.meter_counters[(1, 2)] = (0, 0)
    first = client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"]
    p2 = next(p for p in first if p["port"] == 2)
    assert p2["name"] == "s1-eth2"
    assert p2["qos_in"]["limit_mbps"] == 20 and p2["qos_in"]["measured"] is False and p2["qos_out"] is None

    _time.sleep(0.05)
    fake_ryu.meter_counters[(1, 2)] = (1_000_000, 600_000)  # 60% bị huỷ
    p2 = next(p for p in client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"] if p["port"] == 2)
    q = p2["qos_in"]
    assert q["measured"] is True
    assert q["dropped_mbps"] > 0
    total = q["dropped_mbps"] + q["rx_after_qos_mbps"]
    assert abs(q["dropped_mbps"] / total - 0.6) < 0.01
    # Port không có QoS thì không có số liệu meter
    p1 = next(p for p in client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"] if p["port"] == 1)
    assert p1["qos_in"] is None and p1["qos_out"] is None


def test_rate_window_shared_between_clients(client, admin_headers, fake_ryu, monkeypatch):
    """Hai lần đọc sát nhau (VD hai client cùng poll) trả cùng kết quả, không tính trên cửa sổ quá ngắn"""
    from app.routers import sdn
    sdn.last_port_stats.clear()
    monkeypatch.setattr(sdn, "MIN_RATE_WINDOW_S", 0)
    client.get("/api/sdn/qos/1", headers=admin_headers)
    first = client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"]
    monkeypatch.setattr(sdn, "MIN_RATE_WINDOW_S", 60)
    fake_ryu.ports[1] = [1, 2, 3]
    orig = fake_ryu.get_port_stats

    async def busier(dpid):  # bộ đếm tăng mạnh nhưng chỉ sau vài ms
        return [{**p, "rx_bytes": p["rx_bytes"] + 10**9} if isinstance(p["port_no"], int) else p for p in await orig(dpid)]
    fake_ryu.get_port_stats = busier
    second = client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"]
    assert [p["rx_mbps"] for p in second] == [p["rx_mbps"] for p in first]


def test_concurrent_flow_creation(client, admin_headers, fake_ryu):
    """Thêm luật song song (áp dụng cho nhiều switch) không được lỗi 'database is locked'.
    Lỗi cũ: giữ transaction ghi SQLite qua await Ryu -> request thứ hai chặn event loop."""
    import asyncio
    import httpx
    from app.main import app

    real_add = fake_ryu.add_flow

    async def slow_add(flow):
        await asyncio.sleep(0.3)  # mô phỏng độ trễ gọi Ryu
        await real_add(flow)
    fake_ryu.add_flow = slow_add

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=20) as ac:
            payload = {"src_ip": "10.0.0.4", "dst_ip": "10.0.0.3", "action": "DROP", "priority": 100}
            return await asyncio.gather(*[ac.post("/api/sdn/flows", headers=admin_headers, json={**payload, "dpid": d})
                                          for d in (1, 2)])
    responses = asyncio.run(run())
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert len(fake_ryu.flows[1]) == 1 and len(fake_ryu.flows[2]) == 1


def test_failed_ryu_call_leaves_no_policy(client, admin_headers, fake_ryu):
    """Ryu lỗi giữa chừng -> không để lại bản ghi policy (kể cả bản chưa kích hoạt)"""
    async def boom(flow):
        from app.services.ryu_client import RyuError
        raise RyuError("Ryu lỗi giả lập", status_code=502)
    fake_ryu.add_flow = boom
    res = client.post("/api/sdn/flows", headers=admin_headers,
                      json={"dpid": 1, "src_ip": "10.0.0.1", "action": "DROP", "priority": 100})
    assert res.status_code == 502
    db = SessionLocal()
    assert db.query(FlowPolicy).count() == 0
    db.close()



# ---------- QoS chiều ra (egress) ----------

def test_egress_qos_uses_egress_table(client, admin_headers, fake_ryu):
    res = client.post("/api/sdn/qos/config", headers=admin_headers,
                      json={"dpid": 1, "port": 2, "max_rate_mbps": 8, "direction": "egress"})
    assert res.status_code == 200, res.text
    meter_id = sdn_rules.EGRESS_METER_OFFSET + 2
    assert fake_ryu.meters[1][meter_id]["bands"][0]["rate"] == 8000
    flow = fake_ryu.flows[1][0]
    assert flow["table_id"] == sdn_rules.EGRESS_TABLE and flow["match"] == {"metadata": 2}
    assert flow["actions"] == [{"type": "METER", "meter_id": meter_id}, {"type": "OUTPUT", "port": 2}]
    profiles = client.get("/api/sdn/qos/config/1", headers=admin_headers).json()
    assert [(p["port_no"], p["direction"]) for p in profiles] == [(2, "egress")]


def test_qos_both_directions_and_delete_one(client, admin_headers, fake_ryu):
    res = client.post("/api/sdn/qos/config", headers=admin_headers,
                      json={"dpid": 1, "port": 3, "max_rate_mbps": 10, "direction": "both"})
    assert res.status_code == 200
    assert set(fake_ryu.meters[1]) == {3, sdn_rules.EGRESS_METER_OFFSET + 3}
    assert {f["table_id"] for f in fake_ryu.flows[1]} == {sdn_rules.QOS_TABLE, sdn_rules.EGRESS_TABLE}

    res = client.delete("/api/sdn/qos/config/1/3?direction=egress", headers=admin_headers)
    assert res.status_code == 200
    assert set(fake_ryu.meters[1]) == {3}
    assert [f["table_id"] for f in fake_ryu.flows[1]] == [sdn_rules.QOS_TABLE]
    profiles = client.get("/api/sdn/qos/config/1", headers=admin_headers).json()
    assert [p["direction"] for p in profiles] == ["ingress"]

    # Không truyền direction -> bỏ hết
    assert client.delete("/api/sdn/qos/config/1/3", headers=admin_headers).status_code == 200
    assert fake_ryu.meters[1] == {} and fake_ryu.flows[1] == []


def test_egress_qos_stats(client, admin_headers, fake_ryu, monkeypatch):
    import time as _time
    from app.routers import sdn
    monkeypatch.setattr(sdn, "MIN_RATE_WINDOW_S", 0)
    sdn.last_port_stats.clear()
    sdn.last_meter_stats.clear()
    client.post("/api/sdn/qos/config", headers=admin_headers,
                json={"dpid": 1, "port": 2, "max_rate_mbps": 8, "direction": "egress"})
    mid = sdn_rules.EGRESS_METER_OFFSET + 2
    fake_ryu.meter_counters[(1, mid)] = (0, 0)
    client.get("/api/sdn/qos/1", headers=admin_headers)
    _time.sleep(0.05)
    fake_ryu.meter_counters[(1, mid)] = (1_000_000, 250_000)
    p2 = next(p for p in client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"] if p["port"] == 2)
    q = p2["qos_out"]
    assert p2["qos_in"] is None and q["measured"] is True and q["limit_mbps"] == 8
    assert abs(q["dropped_mbps"] / q["tx_offered_mbps"] - 0.25) < 0.01


def test_sync_reinstalls_egress_qos(client, admin_headers, fake_ryu):
    client.post("/api/sdn/qos/config", headers=admin_headers,
                json={"dpid": 2, "port": 1, "max_rate_mbps": 5, "direction": "egress"})
    fake_ryu.flows[2] = []
    fake_ryu.meters[2] = {}
    assert asyncio.run(sync_once(fake_ryu)) == 2
    assert sdn_rules.EGRESS_METER_OFFSET + 1 in fake_ryu.meters[2]
    assert fake_ryu.flows[2][0]["table_id"] == sdn_rules.EGRESS_TABLE


# ---------- Dữ liệu controller ----------

def test_routing_system_devices_endpoints(client, viewer_headers):
    routing = client.get("/api/sdn/routing", headers=viewer_headers).json()
    assert routing["links"][0]["utilization"] == 0.42
    system = client.get("/api/sdn/system", headers=viewer_headers).json()
    assert system["cpu_percent"] == 12.5
    devices = client.get("/api/sdn/devices", headers=viewer_headers).json()["devices"]
    assert [d["dpid"] for d in devices] == [1, 2]
    assert devices[0]["software"] == "3.3.9" and [p["name"] for p in devices[0]["ports"]] == ["s1-eth1", "s1-eth2", "s1-eth3"]


def test_controller_data_requires_login(client):
    assert client.get("/api/sdn/routing").status_code == 401
    assert client.get("/api/sdn/system").status_code == 401



def test_rate_uses_switch_clock(client, admin_headers, fake_ryu, monkeypatch):
    """Tốc độ phải tính theo đồng hồ của switch (duration_sec/nsec), không theo giờ backend nhận phản hồi.
    Lỗi cũ: thời điểm nhận phản hồi Ryu dao động -> số hiển thị lệch ~43% so với lưu lượng thật."""
    from app.routers import sdn
    sdn.last_port_stats.clear()
    monkeypatch.setattr(sdn, "MIN_RATE_WINDOW_S", 0)
    state = {"bytes": 0, "dur": 100.0}

    async def stats(dpid):
        return [{"port_no": 1, "tx_bytes": state["bytes"], "rx_bytes": 0,
                 "duration_sec": int(state["dur"]), "duration_nsec": int((state["dur"] % 1) * 1e9)}]
    fake_ryu.get_port_stats = stats
    client.get("/api/sdn/qos/1", headers=admin_headers)
    # Switch đọc bộ đếm cách nhau đúng 2 giây, truyền 2.5 MB -> 10 Mbps, dù backend gọi sát nhau
    state["bytes"] += 2_500_000
    state["dur"] += 2.0
    p1 = client.get("/api/sdn/qos/1", headers=admin_headers).json()["stats"][0]
    assert p1["measured"] and abs(p1["tx_mbps"] - 10.0) < 0.01


def test_delete_qos_and_sync_do_not_interleave(client, admin_headers, fake_ryu):
    """Sync worker chạy đúng lúc đang xoá QoS không được cài lại meter vừa xoá (meter "mồ côi")."""
    import httpx
    from app.main import app
    client.post("/api/sdn/qos/config", headers=admin_headers,
                json={"dpid": 1, "port": 2, "max_rate_mbps": 5, "direction": "egress"})
    mid = sdn_rules.EGRESS_METER_OFFSET + 2
    real_delete_meter = fake_ryu.delete_meter

    async def slow_delete_meter(meter):
        await real_delete_meter(meter)
        await asyncio.sleep(0.3)  # khoảng trống giữa gỡ trên switch và xoá DB
    fake_ryu.delete_meter = slow_delete_meter

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=20) as ac:
            delete = asyncio.create_task(ac.delete("/api/sdn/qos/config/1/2?direction=egress", headers=admin_headers))
            await asyncio.sleep(0.1)  # sync chạy khi delete đang ở giữa chừng
            await sync_once(fake_ryu)
            return await delete
    res = asyncio.run(run())
    assert res.status_code == 200
    assert mid not in fake_ryu.meters[1], "sync đã cài lại meter vừa xoá"
    assert fake_ryu.flows[1] == []
