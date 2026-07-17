"""Shared fetch layer reused by every tool.

Static-first: try httpx; fall back to a headless browser only when the static
HTML looks empty / JS-gated. Enforces robots.txt, per-domain rate limiting,
SSRF validation on every redirect hop, and response-size caps.
"""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from .browser import BrowserPool
from .config import Settings
from .security import BlockedURLError, validate_url

# Below this many characters of extracted text we assume the page is JS-gated
# and worth a browser render. ponytail: crude heuristic, tune if it misfires.
_MIN_STATIC_TEXT = 200


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    html: str
    via: str  # "static" | "browser"


# --- per-domain rate limiting -------------------------------------------------
_domain_last: dict[str, float] = {}
_domain_locks: dict[str, asyncio.Lock] = {}


def _lock_for(domain: str) -> asyncio.Lock:
    lock = _domain_locks.get(domain)
    if lock is None:
        lock = _domain_locks[domain] = asyncio.Lock()
    return lock


async def _rate_limit(domain: str, delay: float) -> None:
    async with _lock_for(domain):
        wait = delay - (time.monotonic() - _domain_last.get(domain, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _domain_last[domain] = time.monotonic()


# --- robots.txt ---------------------------------------------------------------
# We fetch robots.txt ourselves (with our UA) and parse the text, rather than
# letting RobotFileParser.read() do its own urllib fetch — that uses urllib's
# default UA, which many sites 403, and a 403 is then read as "disallow all".
# A non-200 robots.txt (404/403/redirect) => treat as allowed (common practice).
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
_robots_locks: dict[str, asyncio.Lock] = {}


async def _robots_for(base: str, s: Settings) -> urllib.robotparser.RobotFileParser:
    cached = _robots_cache.get(base)
    if cached is not None:
        return cached
    lock = _robots_locks.setdefault(base, asyncio.Lock())
    async with lock:
        cached = _robots_cache.get(base)
        if cached is not None:
            return cached
        rp = urllib.robotparser.RobotFileParser()
        robots_url = urljoin(base, "/robots.txt")
        try:
            validate_url(robots_url, allow_private=s.allow_private_networks)
            async with httpx.AsyncClient(
                timeout=s.request_timeout_s,
                headers={"User-Agent": s.user_agent},
                follow_redirects=False,
            ) as client:
                resp = await client.get(robots_url)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.allow_all = True  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - unreachable/invalid robots => allow
            rp.allow_all = True  # type: ignore[attr-defined]
        _robots_cache[base] = rp
        return rp


async def _robots_allows(url: str, s: Settings) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = await _robots_for(base, s)
    return rp.can_fetch(s.user_agent, url)


# --- static fetch with manual redirect validation ----------------------------
async def _fetch_static(url: str, s: Settings) -> FetchResult:
    headers = {"User-Agent": s.user_agent}
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=s.request_timeout_s, headers=headers
    ) as client:
        current = url
        for _ in range(s.max_redirects + 1):
            validate_url(current, allow_private=s.allow_private_networks)
            resp = await client.get(current)
            if resp.is_redirect and resp.next_request is not None:
                current = str(resp.next_request.url)
                continue
            # ponytail: post-hoc size cap; stream-abort if you need hard memory bounds.
            html = resp.text[: s.max_response_bytes]
            return FetchResult(url=str(resp.url), status=resp.status_code, html=html, via="static")
    raise BlockedURLError("too many redirects")


async def _fetch_browser(url: str, s: Settings, pool: BrowserPool) -> FetchResult:
    async with pool.page() as page:
        resp = await page.goto(
            url, timeout=s.request_timeout_s * 1000, wait_until="domcontentloaded"
        )
        try:
            html = await page.content()
        except Exception:
            # Settle down client-side navigations / redirects
            with suppress(Exception):
                await page.wait_for_load_state("load", timeout=5000)
            html = await page.content()

        html = html[: s.max_response_bytes]
        return FetchResult(
            url=page.url, status=resp.status if resp else 0, html=html, via="browser"
        )


def _looks_gated(html: str) -> bool:
    import trafilatura

    text = trafilatura.extract(html) or ""
    return len(text.strip()) < _MIN_STATIC_TEXT


async def fetch(url: str, *, render: bool, settings: Settings, pool: BrowserPool) -> FetchResult:
    """Fetch a URL through the full safety pipeline and return raw HTML."""
    validate_url(url, allow_private=settings.allow_private_networks)
    if settings.respect_robots and not await _robots_allows(url, settings):
        raise BlockedURLError(f"disallowed by robots.txt: {url}")
    await _rate_limit(urlparse(url).netloc, settings.per_domain_delay_s)

    if render:
        return await _fetch_browser(url, settings, pool)

    result = await _fetch_static(url, settings)
    if _looks_gated(result.html):
        return await _fetch_browser(url, settings, pool)
    return result
