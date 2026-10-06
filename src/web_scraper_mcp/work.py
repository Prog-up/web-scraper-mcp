"""Bound blocking work even when its awaiting tool is cancelled or times out."""

import asyncio
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor

from .limits import CapacityError


class WorkPool:
    def __init__(self, maximum: int = 4):
        self.maximum = maximum
        self.active = 0
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=maximum, thread_name_prefix="scraper-work")

    async def run(self, function, *args):
        with self.lock:
            if self.active >= self.maximum:
                raise CapacityError("blocking work capacity reached; retry later")
            self.active += 1
        try:
            future = self.executor.submit(contextvars.copy_context().run, function, *args)
        except BaseException:
            with self.lock:
                self.active -= 1
            raise

        def release(_):
            with self.lock:
                self.active -= 1

        # Cancelling the waiter cannot release the slot of a still-running thread.
        future.add_done_callback(release)
        return await asyncio.wrap_future(future)


work = WorkPool()
