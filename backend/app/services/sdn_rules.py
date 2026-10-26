"""Dựng payload ofctl_rest cho luật firewall và QoS.

Pipeline OpenFlow (phải khớp với sdn_network/sdn_brain.py):
  Table 0 QOS_TABLE      : QoS chiều vào: in_port=P -> meter -> goto 1; mặc định goto 1
  Table 1 POLICY_TABLE   : firewall DROP (không action) / ALLOW (goto 2); mặc định goto 2
  Table 2 FORWARD_TABLE  : luật định tuyến do controller cài (ghi metadata = port ra) -> goto 3
  Table 3 EGRESS_TABLE   : metadata=P -> output P; QoS chiều ra: metadata=P -> meter -> output P

Cookie (32 bit cao = loại, 32 bit thấp = id):
  1: firewall (policy.id)   2: QoS vào (port)   3: định tuyến (controller)
  4: output mặc định bảng egress (controller)   5: QoS ra (port)
"""
from typing import Dict, Any
from app.models.models import FlowPolicy, QoSProfile

QOS_TABLE = 0
POLICY_TABLE = 1
FORWARD_TABLE = 2
EGRESS_TABLE = 3

POLICY_COOKIE_BASE = 0x1 << 32
QOS_COOKIE_BASE = 0x2 << 32
ROUTE_COOKIE_BASE = 0x3 << 32
EGRESS_COOKIE_BASE = 0x4 << 32
QOS_EGRESS_COOKIE_BASE = 0x5 << 32
COOKIE_KIND_MASK = 0xFFFFFFFF << 32
EXACT_MASK = 0xFFFFFFFFFFFFFFFF
METADATA_MASK = 0xFFFFFFFF

QOS_FLOW_PRIORITY = 100
# Meter chiều ra dùng dải id riêng để không trùng meter chiều vào (meter_id = port)
EGRESS_METER_OFFSET = 1000

_COOKIE_KINDS = {
    POLICY_COOKIE_BASE: "policy",
    QOS_COOKIE_BASE: "qos",
    ROUTE_COOKIE_BASE: "route",
    EGRESS_COOKIE_BASE: "system",
    QOS_EGRESS_COOKIE_BASE: "qos",
}


def policy_cookie(policy_id: int) -> int:
    return POLICY_COOKIE_BASE + policy_id


def classify_cookie(cookie: int):
    """Trả về (loại, id) của flow dựa trên cookie"""
    kind = _COOKIE_KINDS.get(cookie & COOKIE_KIND_MASK)
    if kind is None:
        return None, None
    return kind, cookie & 0xFFFFFFFF


def build_match(src_ip, dst_ip) -> Dict[str, Any]:
    match = {"eth_type": 2048}  # IPv4
    if src_ip:
        match["ipv4_src"] = src_ip
    if dst_ip:
        match["ipv4_dst"] = dst_ip
    return match


def policy_actions(action: str):
    # ALLOW: bỏ qua các luật DROP ưu tiên thấp hơn, chuyển sang bảng định tuyến; DROP: không action = huỷ gói
    return [{"type": "GOTO_TABLE", "table_id": FORWARD_TABLE}] if action == "ALLOW" else []


def policy_flow(policy: FlowPolicy) -> Dict[str, Any]:
    return {
        "dpid": int(policy.dpid),
        "cookie": policy_cookie(policy.id),
        "table_id": POLICY_TABLE,
        "idle_timeout": 0,
        "hard_timeout": 0,
        "priority": policy.priority,
        "match": policy.match_conditions,
        "actions": policy_actions(policy.action),
    }


def policy_flow_delete(policy: FlowPolicy) -> Dict[str, Any]:
    return {
        "dpid": int(policy.dpid),
        "cookie": policy_cookie(policy.id),
        "cookie_mask": EXACT_MASK,
        "table_id": POLICY_TABLE,
    }


def qos_meter_id(port_no: int, direction: str = "ingress") -> int:
    # Mỗi port có tối đa 1 meter mỗi chiều
    return port_no if direction == "ingress" else EGRESS_METER_OFFSET + port_no


def qos_meter(profile: QoSProfile) -> Dict[str, Any]:
    rate_kbps = profile.max_bw
    # Burst = 0.5 giây lưu lượng: đo bằng iperf trên OVS 3.3, burst nhỏ hơn (rate/10) làm
    # TCP chỉ đạt ~50% mức đặt; rate/2 cho thông lượng sát mức đặt (5 -> 5.2, 20 -> 21.3 Mbps)
    return {
        "dpid": int(profile.dpid),
        "meter_id": qos_meter_id(profile.port_no, profile.direction),
        "flags": ["KBPS", "BURST"],
        "bands": [{"type": "DROP", "rate": rate_kbps, "burst_size": max(rate_kbps // 2, 100)}],
    }


def qos_cookie(profile: QoSProfile) -> int:
    base = QOS_COOKIE_BASE if profile.direction == "ingress" else QOS_EGRESS_COOKIE_BASE
    return base + profile.port_no


def qos_flow(profile: QoSProfile) -> Dict[str, Any]:
    meter = {"type": "METER", "meter_id": qos_meter_id(profile.port_no, profile.direction)}
    if profile.direction == "ingress":
        table, match = QOS_TABLE, {"in_port": profile.port_no}
        actions = [meter, {"type": "GOTO_TABLE", "table_id": POLICY_TABLE}]
    else:
        # Đè luật output mặc định (priority 1) của bảng egress cho port này
        table, match = EGRESS_TABLE, {"metadata": profile.port_no}
        actions = [meter, {"type": "OUTPUT", "port": profile.port_no}]
    return {
        "dpid": int(profile.dpid),
        "cookie": qos_cookie(profile),
        "table_id": table,
        "idle_timeout": 0,
        "hard_timeout": 0,
        "priority": QOS_FLOW_PRIORITY,
        "match": match,
        "actions": actions,
    }


def qos_flow_delete(profile: QoSProfile) -> Dict[str, Any]:
    return {
        "dpid": int(profile.dpid),
        "cookie": qos_cookie(profile),
        "cookie_mask": EXACT_MASK,
        "table_id": QOS_TABLE if profile.direction == "ingress" else EGRESS_TABLE,
    }
