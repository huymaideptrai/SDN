import asyncio
import httpx
from typing import Dict, Any, List, Optional
from app.core.config import settings


class RyuError(Exception):
    """Lỗi khi gọi Ryu REST API. status_code là mã HTTP backend sẽ trả cho client."""
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RyuSDNClient:
    """Client cho các app ofctl_rest và rest_topology của Ryu"""

    def __init__(self, ryu_url: str, timeout: float = 5.0):
        self.ryu_url = ryu_url.rstrip("/")
        self.timeout = timeout
        self._clients = {}

    def _client(self) -> httpx.AsyncClient:
        """Một AsyncClient dùng chung (giữ kết nối) cho mỗi event loop.
        Tạo client mới cho từng lời gọi tốn ~0.2-0.9 s trên Windows (dựng SSL context + TCP mới) ->
        /api/sdn/devices (12 lời gọi) mất ~3 s và các request chậm chiếm hết 6 kết nối của trình duyệt."""
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None or client.is_closed:
            client = self._clients[loop] = httpx.AsyncClient(
                timeout=self.timeout, limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
        return client

    async def aclose(self):
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def _request(self, method: str, path: str, json: Optional[dict] = None) -> Any:
        try:
            response = await self._client().request(method, f"{self.ryu_url}{path}", json=json)
        except httpx.RequestError as exc:
            raise RyuError(f"Không thể kết nối Ryu ({self.ryu_url}): {exc.__class__.__name__}")

        if response.status_code == 404:
            raise RyuError("Switch không tồn tại hoặc chưa kết nối tới Ryu", status_code=404)
        if response.status_code >= 400:
            raise RyuError(f"Ryu trả về lỗi {response.status_code}: {response.text[:200]}", status_code=502)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ---------- Đọc trạng thái ----------

    async def get_switches(self) -> List[int]:
        return await self._request("GET", "/stats/switches") or []

    async def get_topology(self) -> Dict[str, Any]:
        switches, links, hosts = await asyncio.gather(
            self._request("GET", "/v1.0/topology/switches"),
            self._request("GET", "/v1.0/topology/links"),
            self._request("GET", "/v1.0/topology/hosts"),
        )
        nodes = []
        edges = {}

        # rest_topology trả dpid dạng chuỗi hex 16 ký tự ("0000000000000001")
        for sw in switches or []:
            dpid = int(sw["dpid"], 16)
            nodes.append({"id": f"s{dpid}", "dpid": dpid, "type": "switch",
                          "name": f"Switch {dpid}", "val": 3, "color": "#1f77b4"})

        for host in hosts or []:
            mac = host.get("mac")
            ipv4 = [ip for ip in host.get("ipv4", []) if ip and ip != "0.0.0.0"]
            nodes.append({"id": mac, "type": "host", "mac": mac,
                          "name": ipv4[0] if ipv4 else mac, "val": 1, "color": "#2ca02c"})
            port = host.get("port", {})
            if "dpid" in port:
                target = f"s{int(port['dpid'], 16)}"
                # target_port: tên interface phía switch (VD "s1-eth2"); host không có interface trên switch
                edges[(mac, target)] = {"source": mac, "target": target, "port": int(port["port_no"], 16),
                                        "source_port": None, "target_port": port.get("name")}

        # Ryu trả mỗi link 2 chiều -> gộp lại thành 1 cạnh, giữ tên interface đúng theo từng đầu
        for link in links or []:
            a = f"s{int(link['src']['dpid'], 16)}"
            b = f"s{int(link['dst']['dpid'], 16)}"
            key = tuple(sorted((a, b)))
            names = {a: link["src"].get("name"), b: link["dst"].get("name")}
            edges.setdefault(key, {"source": key[0], "target": key[1],
                                   "source_port": names[key[0]], "target_port": names[key[1]]})

        return {"nodes": nodes, "links": list(edges.values())}

    async def get_flows(self, dpid: int) -> List[Dict[str, Any]]:
        data = await self._request("GET", f"/stats/flow/{dpid}")
        return (data or {}).get(str(dpid), [])

    async def get_port_stats(self, dpid: int) -> List[Dict[str, Any]]:
        data = await self._request("GET", f"/stats/port/{dpid}")
        return (data or {}).get(str(dpid), [])

    async def get_desc(self, dpid: int) -> Dict[str, Any]:
        """Mô tả switch: nhà sản xuất, phần cứng, phiên bản phần mềm (VD Open vSwitch 3.3.9)"""
        data = await self._request("GET", f"/stats/desc/{dpid}")
        return (data or {}).get(str(dpid), {})

    async def get_routing(self) -> Dict[str, Any]:
        """Link, flow đang định tuyến và lịch sử chuyển đường (REST của app sdn_brain)"""
        return await self._request("GET", "/sdn/routing") or {}

    async def get_system(self) -> Dict[str, Any]:
        """CPU / RAM / ổ đĩa của máy chạy controller + tiến trình Ryu, OVS (REST của app sdn_brain)"""
        return await self._request("GET", "/sdn/system") or {}

    async def get_port_desc(self, dpid: int) -> List[Dict[str, Any]]:
        """Mô tả port (có tên interface, VD "s1-eth2")"""
        data = await self._request("GET", f"/stats/portdesc/{dpid}")
        return (data or {}).get(str(dpid), [])

    async def get_meter_stats(self, dpid: int) -> List[Dict[str, Any]]:
        """Bộ đếm meter: byte_in_count (vào meter), band_stats[].byte_band_count (bị band DROP huỷ)"""
        data = await self._request("GET", f"/stats/meter/{dpid}")
        return (data or {}).get(str(dpid), [])

    async def get_meters(self, dpid: int) -> List[Dict[str, Any]]:
        data = await self._request("GET", f"/stats/meterconfig/{dpid}")
        return (data or {}).get(str(dpid), [])

    # ---------- Ghi cấu hình ----------
    # Lưu ý: ofctl_rest gửi lệnh bất đồng bộ, HTTP 200 chỉ có nghĩa là Ryu đã gửi
    # FlowMod/MeterMod tới switch, không đảm bảo switch chấp nhận.

    async def add_flow(self, flow: Dict[str, Any]) -> None:
        await self._request("POST", "/stats/flowentry/add", json=flow)

    async def delete_flow_strict(self, flow: Dict[str, Any]) -> None:
        await self._request("POST", "/stats/flowentry/delete_strict", json=flow)

    async def delete_flows(self, flow: Dict[str, Any]) -> None:
        await self._request("POST", "/stats/flowentry/delete", json=flow)

    async def add_meter(self, meter: Dict[str, Any]) -> None:
        await self._request("POST", "/stats/meterentry/add", json=meter)

    async def modify_meter(self, meter: Dict[str, Any]) -> None:
        await self._request("POST", "/stats/meterentry/modify", json=meter)

    async def delete_meter(self, meter: Dict[str, Any]) -> None:
        await self._request("POST", "/stats/meterentry/delete", json=meter)


ryu_client = RyuSDNClient(settings.RYU_URL, settings.RYU_TIMEOUT)

def get_ryu_client() -> RyuSDNClient:
    """Dependency FastAPI (test có thể override bằng client giả)"""
    return ryu_client
