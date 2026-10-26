import os
import tempfile

# Phải đặt biến môi trường trước khi import app (settings đọc lúc import)
_tmpdir = tempfile.mkdtemp(prefix="sdn_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["SYNC_INTERVAL_SECONDS"] = "3600"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import Base, engine, SessionLocal
from app.models.models import User
from app.core.security import get_password_hash
from app.services.ryu_client import RyuError, get_ryu_client


class FakeRyu:
    """Mô phỏng ofctl_rest: lưu flow/meter trong bộ nhớ"""

    def __init__(self):
        self.switches = [1, 2]
        self.ports = {1: [1, 2, 3], 2: [1, 2, 3]}
        self.flows = {1: [], 2: []}
        self.meters = {1: {}, 2: {}}
        # Bộ đếm meter giả: (byte_in_count, byte_band_count) theo (dpid, meter_id)
        self.meter_counters = {}
        self.down = False

    def _check(self, dpid=None):
        if self.down:
            raise RyuError("Không thể kết nối Ryu")
        if dpid is not None and dpid not in self.switches:
            raise RyuError("Switch không tồn tại", status_code=404)

    async def get_switches(self):
        self._check()
        return list(self.switches)

    async def get_topology(self):
        self._check()
        return {"nodes": [{"id": f"s{d}", "dpid": d, "type": "switch"} for d in self.switches], "links": []}

    async def get_flows(self, dpid):
        self._check(dpid)
        return list(self.flows[dpid])

    async def get_port_stats(self, dpid):
        self._check(dpid)
        return [{"port_no": "LOCAL", "tx_bytes": 0, "rx_bytes": 0}] + [
            {"port_no": p, "tx_bytes": 1000 * p, "rx_bytes": 500 * p} for p in self.ports[dpid]]

    async def get_desc(self, dpid):
        self._check(dpid)
        return {"mfr_desc": "Nicira, Inc.", "hw_desc": "Open vSwitch", "sw_desc": "3.3.9", "dp_desc": f"s{dpid}"}

    async def get_routing(self):
        self._check()
        return {"capacity_mbps": 100, "links": [{"src": 1, "dst": 2, "src_port": 1, "tx_mbps": 42.0, "utilization": 0.42}],
                "flows": [], "events": []}

    async def get_system(self):
        self._check()
        return {"cpu_percent": 12.5, "memory": {"total": 4, "available": 3}, "temperatures": [], "processes": []}

    async def get_port_desc(self, dpid):
        self._check(dpid)
        return [{"port_no": "LOCAL", "name": f"s{dpid}"}] + [{"port_no": p, "name": f"s{dpid}-eth{p}"} for p in self.ports[dpid]]

    async def get_meter_stats(self, dpid):
        self._check(dpid)
        return [{"meter_id": mid, "byte_in_count": self.meter_counters.get((dpid, mid), (0, 0))[0],
                 "band_stats": [{"byte_band_count": self.meter_counters.get((dpid, mid), (0, 0))[1]}]}
                for mid in self.meters[dpid]]

    async def get_meters(self, dpid):
        self._check(dpid)
        return [{"meter_id": mid, **m} for mid, m in self.meters[dpid].items()]

    async def add_flow(self, flow):
        self._check(flow["dpid"])
        table = self.flows[flow["dpid"]]
        table[:] = [f for f in table if not (f["table_id"] == flow["table_id"] and f["priority"] == flow["priority"]
                                              and f["match"] == flow["match"])]
        table.append({**flow, "packet_count": 0, "byte_count": 0})

    async def delete_flows(self, flow):
        self._check(flow["dpid"])
        self.flows[flow["dpid"]] = [f for f in self.flows[flow["dpid"]]
                                    if not (f["cookie"] == flow["cookie"] and f["table_id"] == flow["table_id"])]

    async def delete_flow_strict(self, flow):
        self._check(flow["dpid"])
        self.flows[flow["dpid"]] = [f for f in self.flows[flow["dpid"]]
                                    if not (f["priority"] == flow["priority"] and f["match"] == flow["match"])]

    async def add_meter(self, meter):
        self._check(meter["dpid"])
        assert meter["meter_id"] not in self.meters[meter["dpid"]], "meter đã tồn tại"
        self.meters[meter["dpid"]][meter["meter_id"]] = meter

    async def modify_meter(self, meter):
        self._check(meter["dpid"])
        self.meters[meter["dpid"]][meter["meter_id"]] = meter

    async def delete_meter(self, meter):
        self._check(meter["dpid"])
        self.meters[meter["dpid"]].pop(meter["meter_id"], None)


@pytest.fixture
def fake_ryu():
    return FakeRyu()


@pytest.fixture
def client(fake_ryu):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.add_all([
        User(username="admin", password_hash=get_password_hash("admin123"), role="admin"),
        User(username="viewer", password_hash=get_password_hash("viewer123"), role="viewer"),
    ])
    db.commit()
    db.close()

    app.dependency_overrides[get_ryu_client] = lambda: fake_ryu
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username, password):
    res = client.post("/auth/login", data={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return _login(client, "admin", "admin123")


@pytest.fixture
def viewer_headers(client):
    return _login(client, "viewer", "viewer123")
