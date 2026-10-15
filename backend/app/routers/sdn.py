from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import AuditLog, FlowPolicy
from app.schemas.schemas import FlowPolicyCreate
from app.services.ryu_client import RyuSDNClient
from app.core.dependencies import get_current_user, require_admin, oauth2_scheme
import json
import time

router = APIRouter(prefix="/api/sdn", tags=["SDN Logic"])
ryu_client = RyuSDNClient(ryu_url="http://192.168.179.130:8080")
last_port_stats = {}

@router.get("/topology")
async def get_topology(current_user: dict = Depends(get_current_user)):
    data = await ryu_client.get_topology()
    if data["status"] == "error":
        raise HTTPException(status_code=503, detail=data["message"])
    return data

@router.get("/flows/{dpid}")
async def get_flow_rules(dpid: int, current_user: dict = Depends(get_current_user)):
    res = await ryu_client.get_flows(dpid)
    if res.get("status") == "error":
        return res
    flows = res.get("data", [])
    formatted_flows = []
    
    for flow in flows:
        if flow.get("priority", 0) == 0:
            continue
        formatted_flows.append({
            "table_id": flow.get("table_id"),
            "priority": flow.get("priority"),
            "match": flow.get("match", {}),
            "actions": flow.get("actions", []),
            "packet_count": flow.get("packet_count", 0),
            "byte_count": flow.get("byte_count", 0)
        })
        
    return {"status": "success", "dpid": dpid, "flows": formatted_flows}

@router.post("/flows")
async def create_flow_policy(
    policy: FlowPolicyCreate, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    match = {"eth_type": 2048} 
    
    if policy.src_ip:
        match["ipv4_src"] = policy.src_ip
    if policy.dst_ip:
        match["ipv4_dst"] = policy.dst_ip

    actions = []
    if policy.action.upper() == "ALLOW":
        actions = [{"type": "OUTPUT", "port": "NORMAL"}]
    elif policy.action.upper() == "DROP":
        actions = [] 
    else:
        raise HTTPException(status_code=400, detail="Action chỉ hỗ trợ ALLOW hoặc DROP")

    res = await ryu_client.add_flow(
        dpid=policy.dpid, 
        match=match, 
        actions=actions, 
        priority=policy.priority
    )
    
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message"))

    try:
        new_policy = FlowPolicy(
            dpid=policy.dpid,
            src_ip=policy.src_ip,
            dst_ip=policy.dst_ip,
            action=policy.action.upper(),
            priority=policy.priority
        )
        db.add(new_policy)
        admin_id = current_user.get("id", 1) 
        log = AuditLog(
            user_id=admin_id,
            action=f"Thêm luật {policy.action} cho Switch {policy.dpid}: {policy.src_ip} -> {policy.dst_ip}"
        )
        db.add(log)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Lỗi lưu Database: {e}")

    return {"status": "success", "message": "Đã áp dụng luật mạng thành công"}

@router.get("/qos/{dpid}")
async def get_qos_stats(dpid: int, current_user: dict = Depends(get_current_user)):
    global last_port_stats
    res = await ryu_client.get_port_stats(dpid)
    if res.get("status") == "error":
        return res
        
    stats = res.get("data", [])
    current_time = time.time()
    chart_data = []
    for port in stats:
        port_no = port.get("port_no")
        if str(port_no) == "LOCAL" or (isinstance(port_no, int) and port_no > 100):
            continue

        tx_bytes = port.get("tx_bytes", 0)
        rx_bytes = port.get("rx_bytes", 0)
        port_key = f"{dpid}_{port_no}"
        if port_key in last_port_stats:
            old_data = last_port_stats[port_key]
            time_diff = current_time - old_data["time"]
            if time_diff > 0:
                tx_speed = (tx_bytes - old_data["tx"]) * 8 / (time_diff * 1024 * 1024)
                rx_speed = (rx_bytes - old_data["rx"]) * 8 / (time_diff * 1024 * 1024)
            else:
                tx_speed = rx_speed = 0
        else:
            tx_speed = rx_speed = 0
            
        last_port_stats[port_key] = {
            "tx": tx_bytes,
            "rx": rx_bytes,
            "time": current_time
        }
        
        chart_data.append({
            "port": port_no,
            "tx_mbps": round(tx_speed, 2),
            "rx_mbps": round(rx_speed, 2)
        })
        
    return {"status": "success", "dpid": dpid, "timestamp": time.strftime("%H:%M:%S"), "stats": chart_data}