import asyncio
from types import SimpleNamespace
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, require_admin
from app.models.database import get_db
from app.models.models import AuditLog, SwitchSnmp, User
from app.schemas.schemas import SnmpConfigIn, SnmpConfigOut
from app.services.ryu_client import RyuError, RyuSDNClient, get_ryu_client
from app.services.snmp_client import SnmpCollector, get_snmp_collector, health_cache

router = APIRouter(prefix="/api/devices", tags=["Thiết bị (SNMP)"])


def _out(cfg: SwitchSnmp) -> SnmpConfigOut:
    # Không bao giờ trả community / khoá v3 ra ngoài
    return SnmpConfigOut(
        dpid=int(cfg.dpid), host=cfg.host, port=cfg.port, version=cfg.version,
        has_community=bool(cfg.community), v3_user=cfg.v3_user, v3_auth_proto=cfg.v3_auth_proto,
        v3_priv_proto=cfg.v3_priv_proto, has_auth_key=bool(cfg.v3_auth_key), has_priv_key=bool(cfg.v3_priv_key),
        updated_at=cfg.updated_at,
    )


def _snapshot(cfg: SwitchSnmp) -> SimpleNamespace:
    """Bản sao cấu hình tách khỏi DB session (việc đọc SNMP có thể chạy ở nền sau khi request kết thúc)"""
    return SimpleNamespace(**{k: getattr(cfg, k) for k in (
        "dpid", "host", "port", "version", "community", "v3_user", "v3_auth_proto", "v3_auth_key",
        "v3_priv_proto", "v3_priv_key")})


def _get_cfg(db: Session, dpid: int) -> SwitchSnmp:
    cfg = db.query(SwitchSnmp).filter(SwitchSnmp.dpid == str(dpid)).first()
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Switch {dpid} chưa được cấu hình SNMP")
    return cfg


@router.get("/health")
async def devices_health(db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
                         ryu: RyuSDNClient = Depends(get_ryu_client),
                         collector: SnmpCollector = Depends(get_snmp_collector)):
    """CPU / RAM / lưu trữ / nhiệt độ của từng switch, đọc qua SNMP từ chính thiết bị.
    status: ok | unreachable | error | not_configured (chưa khai báo SNMP, VD switch Mininet)."""
    configs = {int(c.dpid): c for c in db.query(SwitchSnmp).all()}
    controller_ok = True
    try:
        dpids = set(await ryu.get_switches())
    except RyuError:
        controller_ok, dpids = False, set()

    async def one(dpid: int):
        base = {"dpid": dpid, "connected": dpid in dpids}
        cfg = configs.get(dpid)
        if cfg is None:
            return {**base, "status": "not_configured"}
        return {**base, "host": cfg.host, **await health_cache.get(str(dpid), _snapshot(cfg), collector)}

    devices = await asyncio.gather(*[one(d) for d in sorted(dpids | set(configs))])
    return {"status": "success", "controller_ok": controller_ok, "devices": devices}


@router.get("/snmp", response_model=List[SnmpConfigOut])
def list_snmp(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return [_out(c) for c in db.query(SwitchSnmp).order_by(SwitchSnmp.dpid).all()]


@router.put("/snmp/{dpid}", response_model=SnmpConfigOut)
def save_snmp(dpid: int, body: SnmpConfigIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cfg = db.query(SwitchSnmp).filter(SwitchSnmp.dpid == str(dpid)).first()
    creating = cfg is None
    if creating:
        cfg = SwitchSnmp(dpid=str(dpid))
        db.add(cfg)
    cfg.host, cfg.port, cfg.version = body.host, body.port, body.version
    if body.version == "2c":
        if body.community:
            cfg.community = body.community
        if not cfg.community:
            raise HTTPException(status_code=422, detail="SNMPv2c cần community")
        cfg.v3_user = cfg.v3_auth_proto = cfg.v3_auth_key = cfg.v3_priv_proto = cfg.v3_priv_key = None
    else:
        cfg.v3_user = body.v3_user or cfg.v3_user
        if not cfg.v3_user:
            raise HTTPException(status_code=422, detail="SNMPv3 cần tên người dùng")
        cfg.v3_auth_proto, cfg.v3_priv_proto = body.v3_auth_proto, body.v3_priv_proto
        # Khoá bỏ trống = giữ khoá đã lưu; bỏ giao thức = xoá khoá tương ứng
        cfg.v3_auth_key = (body.v3_auth_key or cfg.v3_auth_key) if body.v3_auth_proto else None
        cfg.v3_priv_key = (body.v3_priv_key or cfg.v3_priv_key) if body.v3_priv_proto else None
        if body.v3_auth_proto and not cfg.v3_auth_key:
            raise HTTPException(status_code=422, detail="Cần khoá xác thực (auth key) cho SNMPv3")
        if body.v3_priv_proto and not cfg.v3_priv_key:
            raise HTTPException(status_code=422, detail="Cần khoá mã hoá (priv key) cho SNMPv3")
        cfg.community = None
    db.add(AuditLog(user_id=admin.id, action="SET_SNMP", dpid=str(dpid),
                    details={"host": body.host, "port": body.port, "version": body.version, "created": creating}))
    db.commit()
    db.refresh(cfg)
    health_cache.invalidate(str(dpid))
    return _out(cfg)


@router.delete("/snmp/{dpid}")
def delete_snmp(dpid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    cfg = _get_cfg(db, dpid)
    db.delete(cfg)
    db.add(AuditLog(user_id=admin.id, action="DELETE_SNMP", dpid=str(dpid), details={"host": cfg.host}))
    db.commit()
    health_cache.invalidate(str(dpid))
    return {"status": "success", "message": f"Đã xoá cấu hình SNMP của Switch {dpid}"}


@router.post("/snmp/{dpid}/test")
async def test_snmp(dpid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin),
                    collector: SnmpCollector = Depends(get_snmp_collector)):
    """Kiểm tra kết nối ngay (bỏ qua cache)"""
    cfg = _get_cfg(db, dpid)
    result = await health_cache.get(str(dpid), _snapshot(cfg), collector, force=True)
    return {"dpid": dpid, "host": cfg.host, **result}
