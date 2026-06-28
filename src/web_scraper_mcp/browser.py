"""Shared headless-Chromium pool.

One browser process, contexts handed out under a Semaphore so concurrent pages
stay within RAM/CPU budget. A route filter aborts requests to obviously-private
hosts (SSRF defence inside the browser, where redirects/subresources bypass the
httpx-level check).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from .config import Settings
from .security import host_is_obviously_private

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

# Best-effort fingerprint evasion (self-hosted anti-bot). Optional: if the
# package isn't present we still run, just less stealthy.
try:  # pragma: no cover - import guard
    from playwright_stealth import Stealth  # type: ignore

    _STEALTH: Stealth | None = Stealth()
except Exception:  # noqa: BLE001
    _STEALTH = None


class BrowserPool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._sem = asyncio.Semaphore(settings.max_concurrent_pages)
        self._lock = asyncio.Lock()

    async def _ensure(self) -> Browser:
        async with self._lock:
            if self._browser is None:
                from playwright.async_api import async_playwright

                self._pw = await async_playwright().start()
                # --no-sandbox is only safe because the container is the sandbox.
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
            return self._browser

    async def _guard_route(self, route) -> None:  # noqa: ANN001
        host = urlparse(route.request.url).hostname or ""
        if host_is_obviously_private(host):
            await route.abort()
        else:
            await route.continue_()

    async def _new_context(self, browser: Browser) -> BrowserContext:
        context = await browser.new_context(user_agent=self._settings.user_agent)
        await context.route("**/*", self._guard_route)
        if _STEALTH is not None:
            try:
                await _STEALTH.apply_stealth_async(context)
            except Exception as exc:  # noqa: BLE001
                logger.debug("stealth apply failed: %s", exc)
        return context

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Short-lived page under the concurrency cap (for scrape/crawl/map)."""
        browser = await self._ensure()
        async with self._sem:
            context = await self._new_context(browser)
            page = await context.new_page()
            try:
                yield page
            finally:
                await context.close()

    async def new_session(self) -> tuple[BrowserContext, Page]:
        """Long-lived context+page for the interact tool. Caller must close the context."""
        browser = await self._ensure()
        context = await self._new_context(browser)
        page = await context.new_page()
        return context, page

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
