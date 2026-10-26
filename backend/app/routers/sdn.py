import asyncio
import time
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import AuditLog, FlowPolicy, QoSProfile, User
from app.schemas.schemas import (
    FlowPolicyCreate, FlowPolicyResponse, FlowDelete, QoSConfig, QoSProfileResponse,
)
from app.services.ryu_client import RyuSDNClient, RyuError, get_ryu_client
from app.services import sdn_rules
from app.services.state_lock import with_switch_lock
from app.core.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/sdn", tags=["SDN Logic"])

# Số liệu port lần đo trước, để tính tốc độ theo chênh lệch byte (lưu trong RAM)
last_port_stats = {}
# Số liệu meter lần đo trước (theo dpid_port), để tính tốc độ bị huỷ bởi QoS
last_meter_stats = {}
# Nhiều client cùng poll dùng chung mẫu trước -> cửa sổ đo có thể rất ngắn và lưu lượng có burst
# bị phóng đại. Nếu mẫu trước mới hơn mức này thì trả lại tốc độ đã tính, không đổi mốc.
MIN_RATE_WINDOW_S = 2.0


def _audit(db: Session, user: User, action: str, dpid, details: dict = None):
    db.add(AuditLog(user_id=user.id, action=action, dpid=str(dpid), details=details))


# ---------- Topology ----------

@router.get("/switches")
async def get_switches(current_user: User = Depends(get_current_user),
                       ryu: RyuSDNClient = Depends(get_ryu_client)):
    return {"status": "success", "switches": sorted(await ryu.get_switches())}


@router.get("/topology")
async def get_topology(current_user: User = Depends(get_current_user),
                       ryu: RyuSDNClient = Depends(get_ryu_client)):
    data = await ryu.get_topology()
    return {"status": "success", **data}


# ---------- Flow / Firewall ----------

@router.get("/flows/{dpid}")
async def get_flow_rules(dpid: int, current_user: User = Depends(get_current_user),
                         ryu: RyuSDNClient = Depends(get_ryu_client)):
    flows = await ryu.get_flows(dpid)
    formatted_flows = []
    for flow in flows:
        if flow.get("priority", 0) == 0:  # table-miss / mặc định
            continue
        kind, ref_id = sdn_rules.classify_cookie(flow.get("cookie", 0))
        if kind is None:
            kind = "system"  # VD luật LLDP của Ryu topology
        formatted_flows.append({
            "kind": kind,
            "policy_id": ref_id if kind == "policy" else None,
            "cookie": flow.get("cookie", 0),
            "table_id": flow.get("table_id"),
            "priority": flow.get("priority"),
            "match": flow.get("match", {}),
            "actions": flow.get("actions", []),
            "packet_count": flow.get("packet_count", 0),
            "byte_count": flow.get("byte_count", 0),
        })
    formatted_flows.sort(key=lambda f: (f["table_id"], -f["priority"]))
    return {"status": "success", "dpid": dpid, "flows": formatted_flows}


@router.get("/policies", response_model=List[FlowPolicyResponse])
def list_policies(dpid: Optional[int] = None, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    query = db.query(FlowPolicy).filter(FlowPolicy.is_active == True)
    if dpid is not None:
        query = query.filter(FlowPolicy.dpid == str(dpid))
    return query.order_by(FlowPolicy.id).all()


@router.post("/flows")
@with_switch_lock
async def create_flow_policy(
    policy: FlowPolicyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    ryu: RyuSDNClient = Depends(get_ryu_client),
):
    match = sdn_rules.build_match(policy.src_ip, policy.dst_ip)

    duplicates = db.query(FlowPolicy).filter(
        FlowPolicy.is_active == True,
        FlowPolicy.dpid == str(policy.dpid),
        FlowPolicy.priority == policy.priority,
    ).all()
    if any(p.match_conditions == match for p in duplicates):
        raise HTTPException(status_code=409, detail="Luật với cùng điều kiện và độ ưu tiên đã tồn tại trên switch này")

    # KHÔNG giữ transaction ghi SQLite trong lúc await Ryu: Session đồng bộ chạy trên event loop,
    # request khác chờ khoá sẽ chặn cả loop -> "database is locked". Vì vậy commit bản ghi trước
    # (is_active=False để sync worker chưa cài), gọi Ryu, rồi mới kích hoạt.
    new_policy = FlowPolicy(
        dpid=str(policy.dpid),
        priority=policy.priority,
        match_conditions=match,
        action=policy.action,
        created_by=current_user.id,
        is_active=False,
    )
    db.add(new_policy)
    db.commit()  # lấy id để làm cookie trước khi gửi xuống switch

    try:
        await ryu.add_flow(sdn_rules.policy_flow(new_policy))
    except RyuError:
        db.delete(new_policy)
        db.commit()
        raise

    new_policy.is_active = True
    _audit(db, current_user, "ADD_FLOW_POLICY", policy.dpid, {
        "policy_id": new_policy.id, "src_ip": policy.src_ip, "dst_ip": policy.dst_ip,
        "action": policy.action, "priority": policy.priority,
    })
    db.commit()
    return {"status": "success", "message": "Đã áp dụng luật mạng thành công", "policy_id": new_policy.id}


@router.delete("/policies/{policy_id}")
@with_switch_lock
async def delete_flow_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    ryu: RyuSDNClient = Depends(get_ryu_client),
):
    policy = db.get(FlowPolicy, policy_id)
    if policy is None or not policy.is_active:
        raise HTTPException(status_code=404, detail="Không tìm thấy luật")

    try:
        await ryu.delete_flows(sdn_rules.policy_flow_delete(policy))
    except RyuError as e:
        # Switch đang ngắt kết nối: vẫn vô hiệu hoá trong DB để sync worker không cài lại
        if e.status_code != 404:
            raise

    policy.is_active = False
    _audit(db, current_user, "DELETE_FLOW_POLICY", policy.dpid, {"policy_id": policy.id})
    db.commit()
    return {"status": "success", "message": "Đã xoá luật"}


@router.delete("/flows/{dpid}")
@with_switch_lock
async def delete_raw_flow(
    dpid: int,
    flow: FlowDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    ryu: RyuSDNClient = Depends(get_ryu_client),
):
    """Xoá flow không do backend quản lý (VD: luật học MAC). Luật firewall phải xoá qua /policies/{id}."""
    await ryu.delete_flow_strict({
        "dpid": dpid, "table_id": flow.table_id, "priority": flow.priority, "match": flow.match,
    })
    _audit(db, current_user, "DELETE_FLOW", dpid, flow.model_dump())
    db.commit()
    return {"status": "success", "message": "Đã xoá flow"}


# ---------- QoS ----------

@router.get("/qos/config/{dpid}", response_model=List[QoSProfileResponse])
def list_qos_profiles(dpid: int, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    return db.query(QoSProfile).filter(QoSProfile.dpid == str(dpid)) \
        .order_by(QoSProfile.port_no, QoSProfile.direction).all()


DIRECTION_LABELS = {"ingress": "chiều vào", "egress": "chiều ra"}


@router.post("/qos/config")
@with_switch_lock
async def set_qos(
    config: QoSConfig,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    ryu: RyuSDNClient = Depends(get_ryu_client),
):
    ports = {p.get("port_no") for p in await ryu.get_port_stats(config.dpid)}
    if config.port not in ports:
        raise HTTPException(status_code=400, detail=f"Switch {config.dpid} không có port {config.port}")

    directions = ["ingress", "egress"] if config.direction == "both" else [config.direction]
    rate_kbps = int(config.max_rate_mbps * 1000)
    existing_meters = {m.get("meter_id") for m in await ryu.get_meters(config.dpid)}

    for direction in directions:
        profile = db.query(QoSProfile).filter(
            QoSProfile.dpid == str(config.dpid), QoSProfile.port_no == config.port, QoSProfile.direction == direction
        ).first()
        if profile is None:
            profile = QoSProfile(dpid=str(config.dpid), port_no=config.port, direction=direction, max_bw=rate_kbps)
            db.add(profile)
        profile.max_bw = rate_kbps
        profile.description = config.description

        meter = sdn_rules.qos_meter(profile)
        # Meter phải có trước flow tham chiếu nó (OVS từ chối flow trỏ tới meter chưa tồn tại)
        if meter["meter_id"] in existing_meters:
            await ryu.modify_meter(meter)
        else:
            await ryu.add_meter(meter)
        await ryu.add_flow(sdn_rules.qos_flow(profile))

    _audit(db, current_user, "SET_QOS", config.dpid,
           {"port": config.port, "max_rate_kbps": rate_kbps, "direction": config.direction})
    db.commit()
    label = "cả hai chiều" if config.direction == "both" else DIRECTION_LABELS[config.direction]
    return {"status": "success",
            "message": f"Đã giới hạn port {config.port} ({label}) ở mức {config.max_rate_mbps:g} Mbps"}


@router.delete("/qos/config/{dpid}/{port}")
@with_switch_lock
async def delete_qos(
    dpid: int,
    port: int,
    direction: Optional[Literal["ingress", "egress"]] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    ryu: RyuSDNClient = Depends(get_ryu_client),
):
    """Bỏ QoS của port; không truyền direction = bỏ cả hai chiều"""
    query = db.query(QoSProfile).filter(QoSProfile.dpid == str(dpid), QoSProfile.port_no == port)
    if direction:
        query = query.filter(QoSProfile.direction == direction)
    profiles = query.all()
    if not profiles:
        raise HTTPException(status_code=404, detail="Port này chưa được cấu hình QoS")

    for profile in profiles:
        try:
            # Xoá flow trước rồi mới xoá meter (meter đang được flow tham chiếu)
            await ryu.delete_flows(sdn_rules.qos_flow_delete(profile))
            await ryu.delete_meter({"dpid": dpid, "meter_id": sdn_rules.qos_meter_id(port, profile.direction)})
        except RyuError as e:
            if e.status_code != 404:
                raise
        db.delete(profile)

    removed = [p.direction for p in profiles]
    _audit(db, current_user, "DELETE_QOS", dpid, {"port": port, "direction": ",".join(removed)})
    db.commit()
    label = "cả hai chiều" if len(removed) == 2 else DIRECTION_LABELS[removed[0]]
    return {"status": "success", "message": f"Đã bỏ giới hạn băng thông port {port} ({label})"}


def _switch_clock(stat: dict):
    """Thời điểm switch đọc bộ đếm (giây), từ duration_sec/nsec trong chính bản thống kê.
    Dùng giờ của backend sẽ sai: thời điểm nhận phản hồi Ryu dao động (đã đo được sai lệch ~43%)."""
    if "duration_sec" not in stat:
        return None
    return stat["duration_sec"] + stat.get("duration_nsec", 0) / 1e9


def _rate(store: dict, key: str, now: float, counters: dict, clock=None):
    """Tốc độ (Mbps) của các bộ đếm byte so với mẫu trước; None nếu chưa đo được.
    clock: đồng hồ của switch lúc đọc bộ đếm (ưu tiên); không có thì dùng giờ backend.
    Mẫu trước quá gần (< MIN_RATE_WINDOW_S, VD nhiều client cùng poll) -> trả lại kết quả cũ, giữ mốc."""
    old = store.get(key)
    if old and now - old["time"] < MIN_RATE_WINDOW_S:
        return old["rates"]
    rates = None
    stamp = clock if clock is not None else now
    # Bộ đếm reset (switch khởi động lại / meter tạo lại -> duration cũng reset) -> bỏ mẫu này
    if old and stamp > old["stamp"] and all(counters[k] >= old["counters"][k] for k in counters):
        dt = stamp - old["stamp"]
        rates = {k: (counters[k] - old["counters"][k]) * 8 / (dt * 1_000_000) for k in counters}
    store[key] = {"time": now, "stamp": stamp, "counters": counters, "rates": rates}
    return rates


@router.get("/qos/{dpid}")
async def get_qos_stats(dpid: int, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user),
                        ryu: RyuSDNClient = Depends(get_ryu_client)):
    """Tốc độ từng port (Mbps), tính theo chênh lệch bộ đếm.
    QoS chiều vào: rx_mbps đếm TRƯỚC meter -> kèm rx_after_qos_mbps / dropped_mbps từ bộ đếm meter.
    QoS chiều ra : meter chạy trước khi gói ra port -> tx_mbps đã là lưu lượng SAU QoS;
                   kèm tx_offered_mbps (lưu lượng muốn gửi ra) / dropped_mbps."""
    limits = {(q.port_no, q.direction): q.max_bw for q in db.query(QoSProfile).filter(QoSProfile.dpid == str(dpid))}
    stats, port_desc, meter_stats = await asyncio.gather(
        ryu.get_port_stats(dpid),
        ryu.get_port_desc(dpid),
        ryu.get_meter_stats(dpid) if limits else _empty(),
    )
    names = {p.get("port_no"): p.get("name") for p in port_desc}
    meters = {m.get("meter_id"): m for m in meter_stats}
    now = time.time()
    result = []
    for port in stats:
        port_no = port.get("port_no")
        if not isinstance(port_no, int):  # bỏ port LOCAL
            continue
        port_key = f"{dpid}_{port_no}"
        # measured=False: chưa có mẫu trước để tính tốc độ -> giá trị 0 không phải số đo thật
        rates = _rate(last_port_stats, port_key, now, {"tx": port.get("tx_bytes", 0), "rx": port.get("rx_bytes", 0)},
                      clock=_switch_clock(port))
        item = {"port": port_no, "name": names.get(port_no),
                "tx_mbps": round(rates["tx"], 2) if rates else 0.0,
                "rx_mbps": round(rates["rx"], 2) if rates else 0.0,
                "measured": rates is not None, "qos_in": None, "qos_out": None}

        for direction, field in (("ingress", "qos_in"), ("egress", "qos_out")):
            if (port_no, direction) not in limits:
                continue
            info = {"limit_mbps": limits[(port_no, direction)] / 1000, "measured": False, "dropped_mbps": None}
            meter = meters.get(sdn_rules.qos_meter_id(port_no, direction))
            if meter:
                m_rates = _rate(last_meter_stats, f"{port_key}_{direction}", now, {
                    "in": meter.get("byte_in_count", 0),
                    "drop": sum(b.get("byte_band_count", 0) for b in meter.get("band_stats", [])),
                }, clock=_switch_clock(meter))
                if m_rates:
                    passed = max(m_rates["in"] - m_rates["drop"], 0)
                    info.update(measured=True, dropped_mbps=round(m_rates["drop"], 2))
                    if direction == "ingress":
                        info["rx_after_qos_mbps"] = round(passed, 2)
                    else:
                        info["tx_offered_mbps"] = round(m_rates["in"], 2)
            item[field] = info
        result.append(item)

    result.sort(key=lambda p: p["port"])
    return {"status": "success", "dpid": dpid, "timestamp": time.strftime("%H:%M:%S"), "stats": result}


async def _empty():
    return []


# ---------- Định tuyến / cân bằng tải / tài nguyên (dữ liệu từ controller sdn_brain) ----------

@router.get("/routing")
async def get_routing(current_user: User = Depends(get_current_user),
                      ryu: RyuSDNClient = Depends(get_ryu_client)):
    return {"status": "success", **await ryu.get_routing()}


@router.get("/system")
async def get_system(current_user: User = Depends(get_current_user),
                     ryu: RyuSDNClient = Depends(get_ryu_client)):
    return {"status": "success", **await ryu.get_system()}


@router.get("/devices")
async def get_devices(current_user: User = Depends(get_current_user),
                      ryu: RyuSDNClient = Depends(get_ryu_client)):
    """Thông tin từng switch đọc qua OpenFlow: phần mềm, số port, số flow theo bảng, số meter"""
    dpids = sorted(await ryu.get_switches())
    # Gọi song song cho mọi switch (tuần tự mất ~7 giây với 3 switch)
    replies = await asyncio.gather(*[asyncio.gather(
        ryu.get_desc(d), ryu.get_port_desc(d), ryu.get_flows(d), ryu.get_meters(d)) for d in dpids])
    devices = []
    for dpid, (desc, ports, flows, meters) in zip(dpids, replies):
        per_table = {}
        for f in flows:
            per_table[f.get("table_id")] = per_table.get(f.get("table_id"), 0) + 1
        devices.append({
            "dpid": dpid,
            "name": desc.get("dp_desc") or f"s{dpid}",
            "manufacturer": desc.get("mfr_desc"),
            "hardware": desc.get("hw_desc"),
            "software": desc.get("sw_desc"),
            "ports": [{"port": p["port_no"], "name": p.get("name"), "speed_mbps": round(p.get("curr_speed", 0) / 1000)}
                      for p in ports if isinstance(p.get("port_no"), int)],
            "flows_per_table": {str(k): v for k, v in sorted(per_table.items())},
            "flow_count": len(flows),
            "meter_count": len(meters),
        })
    return {"status": "success", "devices": devices}
