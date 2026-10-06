"""Cancellation must not admit work while the original thread still runs."""

import asyncio
import threading

import pytest

from web_scraper_mcp.limits import CapacityError
from web_scraper_mcp.work import WorkPool


async def test_cancelled_waiter_retains_running_worker_slot():
    pool = WorkPool(1)
    entered = asyncio.Event()
    completed = asyncio.Event()
    loop = asyncio.get_running_loop()
    release = threading.Event()

    def blocking():
        loop.call_soon_threadsafe(entered.set)
        release.wait(2)

    task = asyncio.create_task(pool.run(blocking))
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(CapacityError):
            await pool.run(lambda: None)
        assert pool.active == 1
        pool.executor.submit(lambda: loop.call_soon_threadsafe(completed.set))
        release.set()
        async with asyncio.timeout(1):
            await completed.wait()
        assert await pool.run(lambda: "finished") == "finished"
    finally:
        release.set()
        pool.executor.shutdown(wait=True)
