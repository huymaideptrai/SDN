import httpx
from typing import Dict, Any

class RyuSDNClient:
    def __init__(self, ryu_url: str = "http://192.168.179.130:8080"):
        self.ryu_url = ryu_url
        self.timeout = 5.0

    async def get_topology(self):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                switches_res = await client.get(f"{self.ryu_url}/v1.0/topology/switches")
                links_res = await client.get(f"{self.ryu_url}/v1.0/topology/links")
                hosts_res = await client.get(f"{self.ryu_url}/v1.0/topology/hosts")
                nodes = []
                links = []

                for sw in switches_res.json():
                    dpid = str(sw.get("dpid"))
                    nodes.append({
                        "id": f"s{dpid}", 
                        "name": f"Switch {dpid}", 
                        "val": 3, 
                        "color": "#1f77b4"
                    })

                for host in hosts_res.json():
                    mac = host.get("mac")
                    ip = host.get("ipv4", [mac])[0] if host.get("ipv4") else mac
                    nodes.append({
                        "id": mac, 
                        "name": ip, 
                        "val": 1, 
                        "color": "#2ca02c"
                    })
                
                    port = host.get("port", {})
                    if "dpid" in port:
                        links.append({
                             "source": mac, 
                            "target": f"s{port['dpid']}"
                        })

                for link in links_res.json():
                    links.append({
                        "source": f"s{link['src']['dpid']}",
                        "target": f"s{link['dst']['dpid']}"
                    })

                return {"nodes": nodes, "links": links, "status": "success"}

        except Exception as e:
            return {"status": "error", "message": f"Không thể kết nối Ryu: {str(e)}"}

    async def add_flow(self, dpid: int, match: dict, actions: list, priority: int = 100) -> Dict[str, Any]:
        payload = {
            "dpid": dpid,
            "cookie": 1,
            "cookie_mask": 1,
            "table_id": 0,
            "idle_timeout": 0,
            "hard_timeout": 0,
            "priority": priority,
            "match": match,
            "actions": actions
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(f"{self.url_url}/stats/flowentry/add", json=payload, timeout=self.timeout)
                if response.status_code == 200:
                    return {"status": "success"}
                return {"status": "error", "message": response.text}
            except httpx.RequestError as exc:
                return {"status": "error", "message": f"Lỗi mạng khi gọi Ryu: {exc}"}


    async def get_flows(self, dpid: int):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.ryu_url}/stats/flow/{dpid}")
                data = response.json()
            
                flows = data.get(str(dpid), [])
                return {"status": "success", "data": flows}
        except Exception as e:
            return {"status": "error", "message": f"Lỗi lấy thông số Flows: {str(e)}"}


    async def get_port_stats(self, dpid: int):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.ryu_url}/stats/port/{dpid}")
                data = response.json()
            
                port_stats = data.get(str(dpid), [])
                return {"status": "success", "data": port_stats}
        except Exception as e:
            return {"status": "error", "message": f"Lỗi lấy thông số Port: {str(e)}"}