"""Sandboxed browser; resource traffic is brokered through bounded safe HTTP fetches."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

from .config import Settings
from .limits import Limiter

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright

logger = logging.getLogger(__name__)


@dataclass
class PageState:
    resources: int = 0
    bytes: int = 0
    final_url: str = ""
    error: str | None = None
    allow_writes: bool = False
    write_origin: str | None = None
    allowed_host: str | None = None
    cookies_seen: set[tuple[str, str, str]] = field(default_factory=set)


class BrowserPool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._pages: WeakKeyDictionary = WeakKeyDictionary()
        self._slots = Limiter(settings.max_concurrent_pages)
        self._resource_sem = asyncio.Semaphore(settings.max_concurrent_fetches)
        self.fetch_slots = Limiter(settings.max_concurrent_fetches)
        self._lock = asyncio.Lock()

    def page_state(self, page: Page) -> PageState:
        return self._pages[page]

    async def _ensure(self) -> Browser:
        s = self._settings
        if not s.browser_enabled or not s.egress_proxy_url:
            raise RuntimeError("rendering requires browser_enabled and an isolated guarded proxy")
        endpoint = urlsplit(s.egress_proxy_url)
        if endpoint.scheme != "http" or not endpoint.hostname or endpoint.username:
            raise RuntimeError("browser proxy must be an HTTP endpoint without credentials")
        async with self._lock:
            if self._browser is not None and not self._browser.is_connected():
                await self.close()
            if self._browser is None:
                from playwright.async_api import async_playwright

                self._pw = await async_playwright().start()
                try:
                    self._browser = await self._pw.chromium.launch(
                        headless=True,
                        chromium_sandbox=True,
                        proxy={"server": s.egress_proxy_url, "bypass": "<-loopback>"},
                        args=[
                            "--disable-dev-shm-usage",
                            "--disable-quic",
                            "--disable-background-networking",
                            "--dns-prefetch-disable",
                            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                        ],
                    )
                except BaseException:
                    await self._pw.stop()
                    self._pw = None
                    raise
            return self._browser

    async def _guard_route(self, route) -> None:
        from .fetch import origin, request_http, require_html
        from .security import parse_url

        request = route.request
        if urlsplit(request.url).scheme not in ("http", "https"):
            await route.abort()
            return
        state = self._pages.get(request.frame.page)
        if state is None:
            await route.abort()
            return
        state.resources += 1
        try:
            parse_url(request.url)
            if request.method not in ("GET", "HEAD") and (
                not state.allow_writes or origin(request.url) != state.write_origin
            ):
                raise ValueError("browser writes require an explicit action on the current origin")
            if state.resources > self._settings.browser_resource_limit:
                raise ValueError("browser resource count exceeded")
            remaining = self._settings.browser_total_bytes - state.bytes
            if remaining <= 0:
                raise ValueError("browser total byte limit exceeded")
            async with self._resource_sem:
                result = await request_http(
                    request.url,
                    self._settings,
                    maximum=min(remaining, self._settings.max_response_bytes),
                    headers={
                        k: v
                        for k, v in request.headers.items()
                        if k.lower() not in ("host", "connection", "content-length")
                    },
                    method=request.method,
                    content=request.post_data_buffer
                    if request.method not in ("GET", "HEAD")
                    else None,
                    allowed_host=state.allowed_host,
                    write_origin=state.write_origin if state.allow_writes else None,
                )
            state.bytes += len(result.body)
            if state.bytes > self._settings.browser_total_bytes:
                raise ValueError("browser total byte limit exceeded")
            body = result.body
            # Host-only cookies preserve same-site login/forms without allowing a
            # response to plant cookies on sibling hosts via the privileged API.
            for cookie_url, raw in result.cookies:
                parsed = urlsplit(cookie_url)
                jar = SimpleCookie()
                try:
                    jar.load(raw)
                    for name, value in jar.items():
                        path = value["path"] or parsed.path.rsplit("/", 1)[0] + "/"
                        key = (parsed.hostname or "", path, name)
                        if key not in state.cookies_seen and len(state.cookies_seen) >= 100:
                            continue
                        cookie = {
                            "name": name,
                            "value": value.value,
                            "domain": parsed.hostname,
                            "path": path,
                            "secure": bool(value["secure"]),
                            "httpOnly": bool(value["httponly"]),
                        }
                        if value["max-age"]:
                            import time

                            cookie["expires"] = max(1, time.time() + int(value["max-age"]))
                        elif value["expires"]:
                            from email.utils import parsedate_to_datetime

                            cookie["expires"] = max(
                                1, parsedate_to_datetime(value["expires"]).timestamp()
                            )
                        if value["samesite"].capitalize() in ("Strict", "Lax", "None"):
                            cookie["sameSite"] = value["samesite"].capitalize()
                        await request.frame.page.context.add_cookies([cookie])
                        state.cookies_seen.add(key)
                except Exception:
                    logger.debug("invalid cookie skipped")
            response_headers = {
                k: v for k, v in result.headers.items() if k.lower() != "set-cookie"
            }
            if request.is_navigation_request():
                require_html(result)
                if request.frame == request.frame.page.main_frame:
                    state.final_url = result.url
                if result.url != request.url and "html" in result.headers.get("content-type", ""):
                    from html import escape

                    body = f'<base href="{escape(result.url, quote=True)}">'.encode() + body
            # Never continue to Chromium's network stack or forward a 3xx.
            # The broker has already checked policy on all redirected destinations.
            await route.fulfill(status=result.status, headers=response_headers, body=body)
        except Exception as exc:
            logger.debug("browser resource rejected: %s", type(exc).__name__)
            if request.is_navigation_request():
                state.error = "browser navigation failed destination/content/resource policy"
            await route.abort()

    async def navigate(self, page: Page, url: str, *, allowed_host: str | None = None) -> None:
        """Move to the broker's final URL explicitly, without browser 3xx bypasses."""
        from .security import parse_url

        parse_url(url)
        state = self.page_state(page)
        state.error = None
        state.allowed_host = allowed_host
        for _ in range(self._settings.max_redirects + 1):
            await page.goto(
                url,
                timeout=self._settings.request_timeout_s * 1000,
                wait_until="domcontentloaded",
            )
            if state.error:
                raise ValueError(state.error)
            final = state.final_url or page.url
            if final == page.url:
                return
            url = final
        raise ValueError("browser final URL did not stabilize")

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        async with self._slots.slot():
            browser = await self._ensure()
            context = await browser.new_context(
                user_agent=self._settings.user_agent,
                service_workers="block",
                accept_downloads=False,
            )
            try:
                await context.route("**/*", self._guard_route)

                async def reject_websocket(ws):
                    await ws.close()

                await context.route_web_socket("**/*", reject_websocket)
                if self._settings.browser_stealth:
                    try:
                        from playwright_stealth import Stealth

                        await Stealth().apply_stealth_async(context)
                    except Exception:
                        logger.debug("optional browser fingerprint mitigation unavailable")
                page = await context.new_page()
                page.set_default_timeout(self._settings.request_timeout_s * 1000)
                self._pages[page] = PageState()
                yield page
            finally:
                async with asyncio.timeout(5):
                    await context.close()

    async def close(self) -> None:
        try:
            if self._browser is not None:
                async with asyncio.timeout(5):
                    await self._browser.close()
        finally:
            self._browser = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
