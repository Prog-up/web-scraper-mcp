"""Admission rejects excess work instead of accumulating unbounded waiters."""

from contextlib import asynccontextmanager


class CapacityError(RuntimeError):
    pass


class Limiter:
    def __init__(self, maximum: int):
        self.maximum = maximum
        self.active = 0

    @asynccontextmanager
    async def slot(self):
        # No await between testing and incrementing: atomic on our async event loop.
        if self.active >= self.maximum:
            raise CapacityError("service capacity reached; retry later")
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
