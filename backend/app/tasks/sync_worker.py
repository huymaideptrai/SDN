import asyncio
from app.services.ryu_client import RyuSDNClient
from app.models.database import SessionLocal
from app.models.models import FlowPolicy

# Khởi tạo client kết nối Ryu
ryu = RyuSDNClient(ryu_url="http://192.168.179.130:8080")

network_cache = {
    "topology": {},
    "port_stats": {}
}

async def poll_ryu_stats():
    """Nhiệm vụ 1: Lấy Topology và Port Stats mỗi 2 giây lưu vào RAM"""
    while True:
        try:
            topo_data = await ryu.get_topology()
            if topo_data.get("status") == "success":
                network_cache["topology"] = topo_data
        except Exception as e:
            print(f"[Cache Worker] Lỗi kết nối Ryu: {e}")
            
        await asyncio.sleep(2)

async def sync_flow_state():
    """Nhiệm vụ 2: Đồng bộ luật từ DB xuống Ryu mỗi 30 giây"""
    while True:
        db = SessionLocal()
        try:
            active_flows = db.query(FlowPolicy).filter(FlowPolicy.is_active == True).all()
            for flow in active_flows:
                await ryu.add_flow(
                    dpid=int(flow.dpid),
                    match=flow.match_conditions,
                    actions=flow.action,
                    priority=flow.priority
                )
        except Exception as e:
            print(f"[Sync Worker] Lỗi đồng bộ DB: {e}")
        finally:
            db.close()
            
        await asyncio.sleep(30)