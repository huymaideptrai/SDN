import asyncio
import logging
from collections import defaultdict
from app.core.config import settings
from app.services.ryu_client import RyuSDNClient, RyuError, ryu_client
from app.services import sdn_rules
from app.services.state_lock import switch_state_lock
from app.models.database import SessionLocal
from app.models.models import FlowPolicy, QoSProfile

# Dùng logger của uvicorn để log hiện cùng log server. Không dùng print: khi stdout bị
# chuyển hướng ra file trên Windows (cp1252), print tiếng Việt ném UnicodeEncodeError
# và làm chết vòng lặp sync; logging tự xử lý lỗi ghi log thay vì ném exception.
logger = logging.getLogger("uvicorn.error")


async def sync_switch(ryu: RyuSDNClient, dpid: int, policies, profiles) -> int:
    """Cài lại các luật/meter có trong DB nhưng đang thiếu trên switch. Trả về số mục đã cài bù."""
    installed = 0
    cookies = {f.get("cookie") for f in await ryu.get_flows(dpid)}

    if profiles:
        meters = {m.get("meter_id") for m in await ryu.get_meters(dpid)}
        for profile in profiles:
            meter = sdn_rules.qos_meter(profile)
            if meter["meter_id"] not in meters:
                await ryu.add_meter(meter)
                installed += 1
            flow = sdn_rules.qos_flow(profile)
            if flow["cookie"] not in cookies:
                await ryu.add_flow(flow)
                installed += 1

    # Chỉ cài bù flow còn thiếu: cài lại flow đang tồn tại sẽ reset bộ đếm packet/byte
    for policy in policies:
        flow = sdn_rules.policy_flow(policy)
        if flow["cookie"] not in cookies:
            await ryu.add_flow(flow)
            installed += 1
    return installed


async def sync_once(ryu: RyuSDNClient = ryu_client) -> int:
    # Không chạy xen kẽ với endpoint đang thêm/xoá luật (tránh cài lại thứ vừa bị xoá)
    async with switch_state_lock():
        return await _sync_once(ryu)


async def _sync_once(ryu: RyuSDNClient) -> int:
    db = SessionLocal()
    try:
        policies = defaultdict(list)
        for p in db.query(FlowPolicy).filter(FlowPolicy.is_active == True).all():
            policies[int(p.dpid)].append(p)
        profiles = defaultdict(list)
        for q in db.query(QoSProfile).all():
            profiles[int(q.dpid)].append(q)

        total = 0
        for dpid in await ryu.get_switches():
            if policies[dpid] or profiles[dpid]:
                total += await sync_switch(ryu, dpid, policies[dpid], profiles[dpid])
        return total
    finally:
        db.close()


async def sync_flow_state():
    """Đồng bộ luật từ DB xuống switch theo chu kỳ (khôi phục sau khi Ryu/switch khởi động lại).
    Vòng lặp không được dừng vì bất kỳ lỗi nào, chỉ dừng khi bị cancel lúc tắt server."""
    while True:
        try:
            installed = await sync_once()
            if installed:
                logger.info("[Sync Worker] Đã cài bù %d luật/meter xuống switch", installed)
        except asyncio.CancelledError:
            raise
        except RyuError as e:
            logger.warning("[Sync Worker] %s", e.message)
        except Exception:
            logger.exception("[Sync Worker] Lỗi đồng bộ")

        await asyncio.sleep(settings.SYNC_INTERVAL_SECONDS)
