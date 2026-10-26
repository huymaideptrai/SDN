"""Thu thập tài nguyên phần cứng của switch thật qua SNMP.

OpenFlow không có CPU/RAM/nhiệt độ; switch Mininet (OVS phần mềm) cũng không có. Switch thật cung cấp
qua SNMP. Thử MIB chuẩn trước, MIB của Cisco làm dự phòng; số liệu nào thiết bị không trả thì để None
(giao diện hiện "thiết bị không cung cấp"), không bao giờ tự suy đoán.

  Thông tin chung : SNMPv2-MIB  sysDescr / sysName / sysUpTime
  CPU             : HOST-RESOURCES-MIB hrProcessorLoad          | CISCO-PROCESS-MIB cpmCPUTotal1minRev
  RAM / lưu trữ   : HOST-RESOURCES-MIB hrStorage (Ram, FixedDisk, FlashMemory) | CISCO-MEMORY-POOL-MIB
  Nhiệt độ        : ENTITY-SENSOR-MIB (RFC 3433, type=celsius)  | CISCO-ENVMON-MIB
"""
import asyncio
import time
from typing import Any, Dict, List, Optional

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, UsmUserData,
    get_cmd, walk_cmd,
    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol, usmHMAC192SHA256AuthProtocol,
    usmAesCfb128Protocol, usmDESPrivProtocol, usmNoAuthProtocol, usmNoPrivProtocol,
)

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"

HR_PROCESSOR_LOAD = "1.3.6.1.2.1.25.3.3.1.2"
HR_STORAGE_TYPE = "1.3.6.1.2.1.25.2.3.1.2"
HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
HR_STORAGE_UNITS = "1.3.6.1.2.1.25.2.3.1.4"
HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"
HR_STORAGE_RAM = "1.3.6.1.2.1.25.2.1.2"
HR_STORAGE_DISK_TYPES = {"1.3.6.1.2.1.25.2.1.4", "1.3.6.1.2.1.25.2.1.9"}  # FixedDisk, FlashMemory

ENT_PHYSICAL_NAME = "1.3.6.1.2.1.47.1.1.1.1.7"
ENT_SENSOR_TYPE = "1.3.6.1.2.1.99.1.1.1.1"
ENT_SENSOR_SCALE = "1.3.6.1.2.1.99.1.1.1.2"
ENT_SENSOR_PRECISION = "1.3.6.1.2.1.99.1.1.1.3"
ENT_SENSOR_VALUE = "1.3.6.1.2.1.99.1.1.1.4"
ENT_SENSOR_STATUS = "1.3.6.1.2.1.99.1.1.1.5"
SENSOR_CELSIUS = 8
SENSOR_OK = 1

CISCO_CPU_1MIN = "1.3.6.1.4.1.9.9.109.1.1.1.1.7"
CISCO_MEMPOOL_NAME = "1.3.6.1.4.1.9.9.48.1.1.1.2"
CISCO_MEMPOOL_USED = "1.3.6.1.4.1.9.9.48.1.1.1.5"
CISCO_MEMPOOL_FREE = "1.3.6.1.4.1.9.9.48.1.1.1.6"
CISCO_TEMP_DESCR = "1.3.6.1.4.1.9.9.13.1.3.1.2"
CISCO_TEMP_VALUE = "1.3.6.1.4.1.9.9.13.1.3.1.3"

AUTH_PROTOCOLS = {None: usmNoAuthProtocol, "MD5": usmHMACMD5AuthProtocol, "SHA": usmHMACSHAAuthProtocol,
                  "SHA256": usmHMAC192SHA256AuthProtocol}
PRIV_PROTOCOLS = {None: usmNoPrivProtocol, "DES": usmDESPrivProtocol, "AES": usmAesCfb128Protocol}


class SnmpError(Exception):
    pass


class SnmpCollector:
    """Đọc số liệu từ một thiết bị theo cấu hình (đối tượng có host, port, version, community, v3_*)."""

    def __init__(self, timeout: float = 2.0, retries: int = 1):
        self.timeout = timeout
        self.retries = retries

    def _auth(self, cfg):
        if cfg.version == "3":
            return UsmUserData(cfg.v3_user, authKey=cfg.v3_auth_key or None, privKey=cfg.v3_priv_key or None,
                               authProtocol=AUTH_PROTOCOLS[cfg.v3_auth_proto], privProtocol=PRIV_PROTOCOLS[cfg.v3_priv_proto])
        return CommunityData(cfg.community, mpModel=1)  # mpModel=1: SNMPv2c

    async def _target(self, cfg):
        return await UdpTransportTarget.create((cfg.host, cfg.port), timeout=self.timeout, retries=self.retries)

    async def _get(self, engine, cfg, target, *oids) -> Dict[str, Any]:
        err_ind, err_status, _, var_binds = await get_cmd(
            engine, self._auth(cfg), target, ContextData(), *[ObjectType(ObjectIdentity(o)) for o in oids])
        if err_ind:
            raise SnmpError(str(err_ind))
        if err_status:
            raise SnmpError(err_status.prettyPrint())
        out = {}
        for name, value in var_binds:
            if value.__class__.__name__ not in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                out[str(name)] = value
        return out

    async def _walk(self, engine, cfg, target, oid) -> Dict[str, Any]:
        """Walk một nhánh; trả {phần index sau oid: giá trị}. Nhánh không tồn tại -> {}"""
        out = {}
        async for err_ind, err_status, _, var_binds in walk_cmd(
                engine, self._auth(cfg), target, ContextData(), ObjectType(ObjectIdentity(oid)),
                lexicographicMode=False):
            if err_ind:
                raise SnmpError(str(err_ind))
            if err_status:
                break
            for name, value in var_binds:
                key = str(name)
                if key.startswith(oid + "."):
                    out[key[len(oid) + 1:]] = value
        return out

    async def collect(self, cfg) -> Dict[str, Any]:
        # Mỗi lần đọc dùng SnmpEngine RIÊNG rồi đóng lại. Engine dùng chung: một thiết bị không phản hồi
        # (Windows báo ICMP port-unreachable trên socket UDP chung) làm MỌI lần đọc song song thất bại
        # và engine hỏng luôn cho các lần sau -> một switch tắt làm cả thẻ phần cứng ngừng hoạt động.
        engine = SnmpEngine()
        try:
            return await self._collect(engine, cfg)
        finally:
            engine.close_dispatcher()

    async def _collect(self, engine, cfg) -> Dict[str, Any]:
        target = await self._target(cfg)
        base = await self._get(engine, cfg, target, SYS_DESCR, SYS_NAME, SYS_UPTIME)
        if not base:
            raise SnmpError("Thiết bị không trả thông tin hệ thống (SNMPv2-MIB)")
        result = {
            "sys_descr": str(base.get(SYS_DESCR, "")) or None,
            "sys_name": str(base.get(SYS_NAME, "")) or None,
            "uptime_s": int(base[SYS_UPTIME]) // 100 if SYS_UPTIME in base else None,  # TimeTicks = 1/100 giây
        }
        cpu, memory_storage, temps = await asyncio.gather(
            self._cpu(engine, cfg, target), self._memory_storage(engine, cfg, target), self._temperatures(engine, cfg, target))
        result["cpu"] = cpu
        result["memory"], result["storage"] = memory_storage
        result["temperatures"] = temps
        return result

    async def _cpu(self, engine, cfg, target) -> Optional[Dict[str, Any]]:
        loads = [int(v) for v in (await self._walk(engine, cfg, target, HR_PROCESSOR_LOAD)).values()]
        if loads:
            return {"percent": round(sum(loads) / len(loads), 1), "cores": len(loads), "source": "HOST-RESOURCES-MIB"}
        cisco = [int(v) for v in (await self._walk(engine, cfg, target, CISCO_CPU_1MIN)).values()]
        if cisco:
            return {"percent": float(max(cisco)), "cores": len(cisco), "source": "CISCO-PROCESS-MIB"}
        return None

    async def _memory_storage(self, engine, cfg, target):
        types = await self._walk(engine, cfg, target, HR_STORAGE_TYPE)
        memory, storage = None, []
        if types:
            descr, units, size, used = await asyncio.gather(*[self._walk(engine, cfg, target, o) for o in
                                                              (HR_STORAGE_DESCR, HR_STORAGE_UNITS, HR_STORAGE_SIZE, HR_STORAGE_USED)])
            for idx, t in types.items():
                t = str(t)
                if idx not in size or idx not in units:
                    continue
                unit = int(units[idx])
                entry = {"name": str(descr.get(idx, idx)), "total": int(size[idx]) * unit,
                         "used": int(used.get(idx, 0)) * unit}
                if t == HR_STORAGE_RAM and memory is None:
                    memory = {**entry, "source": "HOST-RESOURCES-MIB"}
                elif t in HR_STORAGE_DISK_TYPES and entry["total"] > 0:
                    storage.append({**entry, "source": "HOST-RESOURCES-MIB"})
        if memory is None:
            names, used_, free = await asyncio.gather(*[self._walk(engine, cfg, target, o) for o in
                                                         (CISCO_MEMPOOL_NAME, CISCO_MEMPOOL_USED, CISCO_MEMPOOL_FREE)])
            if used_:
                # Pool "Processor" là RAM chính; không có thì cộng mọi pool
                idx = next((i for i, n in names.items() if str(n).lower().startswith("processor")), None)
                indices = [idx] if idx else list(used_)
                u = sum(int(used_[i]) for i in indices if i in used_)
                f = sum(int(free[i]) for i in indices if i in free)
                memory = {"name": str(names.get(idx, "Memory")) if idx else "Memory", "total": u + f, "used": u,
                          "source": "CISCO-MEMORY-POOL-MIB"}
        return memory, storage

    async def _temperatures(self, engine, cfg, target) -> List[Dict[str, Any]]:
        types = await self._walk(engine, cfg, target, ENT_SENSOR_TYPE)
        celsius_idx = [i for i, t in types.items() if int(t) == SENSOR_CELSIUS]
        temps = []
        if celsius_idx:
            scale, precision, value, status, names = await asyncio.gather(*[self._walk(engine, cfg, target, o) for o in
                (ENT_SENSOR_SCALE, ENT_SENSOR_PRECISION, ENT_SENSOR_VALUE, ENT_SENSOR_STATUS, ENT_PHYSICAL_NAME)])
            for i in celsius_idx:
                if i not in value or int(status.get(i, SENSOR_OK)) != SENSOR_OK:
                    continue
                # Giá trị thật = value * 10^(3*(scale-9)) / 10^precision (scale 9 = units)
                celsius = int(value[i]) * 10 ** (3 * (int(scale.get(i, 9)) - 9)) / 10 ** int(precision.get(i, 0))
                temps.append({"name": str(names.get(i, f"Sensor {i}")), "celsius": round(celsius, 1),
                              "source": "ENTITY-SENSOR-MIB"})
        if not temps:
            descr, value = await asyncio.gather(self._walk(engine, cfg, target, CISCO_TEMP_DESCR),
                                                self._walk(engine, cfg, target, CISCO_TEMP_VALUE))
            temps = [{"name": str(descr.get(i, f"Sensor {i}")), "celsius": float(int(v)), "source": "CISCO-ENVMON-MIB"}
                     for i, v in value.items()]
        return temps


class HealthCache:
    """Cache kết quả theo dpid, kiểu "trả dữ liệu cũ, làm mới ở nền":
    - nhiều trình duyệt cùng xem không làm switch bị hỏi dồn dập (tối đa 1 lần đọc / ttl / switch);
    - switch không phản hồi (chờ hết timeout SNMP) không làm chậm cả API: hết hạn thì trả ngay kết quả
      gần nhất (kèm stale=True, collected_at) và đọc lại ở nền. Chỉ lần đầu tiên mới phải chờ."""

    def __init__(self, ttl: float = 15.0):
        self.ttl = ttl
        self._data = {}
        self._locks = {}
        self._refreshing = {}  # dpid -> task (giữ tham chiếu để task nền không bị thu hồi)

    def invalidate(self, dpid: str):
        self._data.pop(dpid, None)

    async def get(self, dpid: str, cfg, collector: SnmpCollector, force: bool = False) -> Dict[str, Any]:
        entry = self._data.get(dpid)
        if entry and not force:
            fresh = time.time() - entry["_at"] < self.ttl
            if not fresh and dpid not in self._refreshing:
                task = asyncio.create_task(self._refresh(dpid, cfg, collector))
                self._refreshing[dpid] = task
                task.add_done_callback(lambda _t, d=dpid: self._refreshing.pop(d, None))
            return {**entry["value"], "stale": not fresh}
        return {**await self._refresh(dpid, cfg, collector, force=force), "stale": False}

    async def _refresh(self, dpid: str, cfg, collector: SnmpCollector, force: bool = False) -> Dict[str, Any]:
        lock = self._locks.setdefault(dpid, asyncio.Lock())
        async with lock:
            cached = self._data.get(dpid)
            if not force and cached and time.time() - cached["_at"] < self.ttl:
                return cached["value"]  # request khác vừa đọc xong
            try:
                value = {"status": "ok", **await collector.collect(cfg)}
            except SnmpError as e:
                value = {"status": "unreachable", "error": str(e)}
            except Exception as e:  # cấu hình sai (VD khoá v3 quá ngắn) -> báo lỗi, không làm hỏng cả trang
                value = {"status": "error", "error": f"{e.__class__.__name__}: {e}"}
            value["collected_at"] = time.time()
            self._data[dpid] = {"_at": time.time(), "value": value}
            return value


snmp_collector = SnmpCollector()
health_cache = HealthCache()


def get_snmp_collector() -> SnmpCollector:
    """Dependency FastAPI (test override bằng collector giả)"""
    return snmp_collector
