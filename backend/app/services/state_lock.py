"""Khoá chung cho mọi thao tác thay đổi cấu hình switch (firewall, QoS) và sync worker.

Vì sao cần: endpoint xoá gỡ luật/meter khỏi switch rồi mới xoá DB (có await ở giữa). Nếu sync worker
chạy đúng lúc đó, nó thấy DB còn bản ghi nhưng switch thiếu -> cài lại -> luật/meter "mồ côi" còn trên
switch dù DB đã xoá (VD luật chặn vẫn chạy). Khoá đảm bảo hai bên không chạy xen kẽ.
"""
import asyncio
import functools

_locks = {}


def switch_state_lock() -> asyncio.Lock:
    """Một khoá cho mỗi event loop (pytest / TestClient có thể chạy nhiều loop khác nhau)"""
    loop = asyncio.get_running_loop()
    lock = _locks.get(loop)
    if lock is None:
        lock = _locks[loop] = asyncio.Lock()
    return lock


def with_switch_lock(func):
    """Decorator cho endpoint async thay đổi cấu hình switch. functools.wraps giữ chữ ký để
    FastAPI vẫn đọc được các Depends của endpoint."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with switch_state_lock():
            return await func(*args, **kwargs)
    return wrapper
