import asyncio
import threading

import pytest

from shop.config import Settings
from shop.storage import Storage


async def test_cancelled_uploads_keep_slots_until_io_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = Storage(Settings())
    release = threading.Event()
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    lock = threading.Lock()
    active = peak = started = 0

    def blocked(**kwargs: object) -> None:
        nonlocal active, peak, started
        with lock:
            active += 1
            started += 1
            peak = max(peak, active)
            if started == 4:
                loop.call_soon_threadsafe(entered.set)
        release.wait(3)
        with lock:
            active -= 1

    monkeypatch.setattr(storage.client, "put_object", blocked)
    try:
        for _wave in range(3):
            tasks = [asyncio.create_task(storage.put(str(i), b"x", "image/png")) for i in range(4)]
            if _wave == 0:
                await asyncio.wait_for(entered.wait(), timeout=2)
            else:
                await asyncio.sleep(0.05)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert peak <= 4 and started == 4
    finally:
        release.set()
        await storage.close()
