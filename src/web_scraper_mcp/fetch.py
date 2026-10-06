"""Bounded, static-first fetching with destination policy on every HTTP hop."""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from .browser import BrowserPool
from .config import Settings
from .security import BlockedURLError, parse_url
from .transport import public_client
from .work import work


class FetchError(ValueError):
    """A fetch failed status, content, time or resource policy."""


@dataclass
class FetchResult:
    url: str
    status: int
    html: str
    via: str


@dataclass
class HTTPResult:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    cookies: list[tuple[str, str]] = field(default_factory=list)

    def text(self) -> str:
        response = httpx.Response(self.status, headers=self.headers, content=self.body)
        return response.text


@dataclass
class DomainState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last: float = 0
    expires: float = 0
    users: int = 0


_domain_states: OrderedDict[str, DomainState] = OrderedDict()
_robots_cache: OrderedDict[str, tuple[float, urllib.robotparser.RobotFileParser]] = OrderedDict()


def origin(url: str) -> str:
    host, port = parse_url(url)
    authority = f"[{host.lower()}]" if ":" in host else host.lower()
    return f"{urlsplit(url).scheme}://{authority}:{port}"


async def _rate_limit(url: str, s: Settings) -> None:
    key = origin(url)
    now = time.monotonic()
    for name, existing in list(_domain_states.items()):
        if not existing.users and existing.expires <= now:
            del _domain_states[name]
    state = _domain_states.get(key)
    if state is None:
        if len(_domain_states) >= s.cache_entries:
            inactive = next((k for k, v in _domain_states.items() if not v.users), None)
            if inactive is None:
                raise FetchError("domain rate-limit capacity reached")
            del _domain_states[inactive]
        state = _domain_states[key] = DomainState()
    _domain_states.move_to_end(key)
    state.users += 1
    try:
        async with state.lock:
            wait = s.per_domain_delay_s - (time.monotonic() - state.last)
            if wait > 0:
                await asyncio.sleep(wait)
            state.last = time.monotonic()
            state.expires = state.last + s.cache_ttl_s
    finally:
        state.users -= 1


async def read_body(response: httpx.Response, maximum: int) -> bytes:
    """Bound wire and decoded bytes; compressed output never allocates past the cap."""
    if response.is_stream_consumed:
        if len(response.content) > maximum:
            raise FetchError("response exceeds byte limit")
        return response.content
    encoding = response.headers.get("content-encoding", "identity").lower()
    decoder = None
    if encoding == "gzip":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decoder = zlib.decompressobj()
    elif encoding not in ("", "identity"):
        raise FetchError("unsupported response compression")
    body = bytearray()
    wire_bytes = 0
    try:
        async for chunk in response.aiter_raw(chunk_size=min(maximum + 1, 16_384)):
            wire_bytes += len(chunk)
            if wire_bytes > maximum:
                raise FetchError("response exceeds wire byte limit")
            decoded = decoder.decompress(chunk, maximum - len(body) + 1) if decoder else chunk
            if len(body) + len(decoded) > maximum:
                raise FetchError("response exceeds decoded byte limit")
            body.extend(decoded)
        if decoder and (not decoder.eof or decoder.unused_data):
            raise FetchError("invalid or concatenated compressed response")
    except zlib.error as exc:
        raise FetchError("invalid response compression") from exc
    return bytes(body)


async def _robots_for(url: str, s: Settings) -> urllib.robotparser.RobotFileParser:
    base = origin(url)
    now = time.monotonic()
    cached = _robots_cache.get(base)
    if cached and cached[0] > now:
        _robots_cache.move_to_end(base)
        return cached[1]
    result = await request_http(urljoin(base, "/robots.txt"), s, policy=False, maximum=64_000)
    rp = urllib.robotparser.RobotFileParser()
    if result.status == 200:
        rp.parse(result.text().splitlines())
    elif result.status in (404, 410):
        rp.parse(["User-agent: *", "Allow: /"])
    else:
        rp.parse(["User-agent: *", "Disallow: /"])
    _robots_cache[base] = (now + s.cache_ttl_s, rp)
    _robots_cache.move_to_end(base)
    while len(_robots_cache) > s.cache_entries:
        _robots_cache.popitem(last=False)
    return rp


async def check_policy(url: str, s: Settings) -> None:
    parse_url(url)
    if s.respect_robots:
        rp = await _robots_for(url, s)
        if not rp.can_fetch(s.user_agent, url):
            raise BlockedURLError("destination disallowed by robots.txt")
    await _rate_limit(url, s)


async def request_http(
    url: str,
    s: Settings,
    *,
    policy: bool = True,
    maximum: int | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    content: bytes | None = None,
    allowed_host: str | None = None,
    write_origin: str | None = None,
) -> HTTPResult:
    if method not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        raise FetchError("unsupported HTTP method")
    if content and len(content) > s.max_request_bytes:
        raise FetchError("request body exceeds byte limit")
    maximum = maximum or s.max_response_bytes
    async with asyncio.timeout(s.request_timeout_s), public_client(s) as client:
        current = url
        request_headers = dict(headers or {})
        request_headers["accept-encoding"] = "identity"
        cookies: list[tuple[str, str]] = []
        for hop in range(s.max_redirects + 1):
            parse_url(current)
            if allowed_host:
                from .parse import same_host

                if not same_host(current, allowed_host):
                    raise BlockedURLError("destination left permitted host")
            if method not in ("GET", "HEAD") and write_origin != origin(current):
                raise BlockedURLError("write destination left explicitly authorized origin")
            if policy:
                await check_policy(current, s)
            else:
                await _rate_limit(current, s)
            async with client.stream(
                method, current, headers=request_headers, content=content
            ) as response:
                for cookie in response.headers.get_list("set-cookie"):
                    if len(cookies) < 32:
                        cookies.append((str(response.url), cookie))
                if response.is_redirect:
                    if hop == s.max_redirects:
                        raise FetchError("too many redirects")
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("redirect has no location")
                    target = urljoin(current, location)
                    parse_url(target)
                    if origin(target) != origin(current):
                        request_headers = {
                            k: v
                            for k, v in request_headers.items()
                            if k.lower() not in ("authorization", "cookie")
                        }
                    if (
                        response.status_code == 303
                        and method != "HEAD"
                        or (response.status_code in (301, 302) and method == "POST")
                    ):
                        method, content = "GET", None
                        request_headers = {
                            k: v
                            for k, v in request_headers.items()
                            if k.lower() not in ("content-type", "content-length")
                        }
                    current = target
                    continue
                body = await read_body(response, maximum)
                # Bodies have been decompressed, never forward stale lengths/encodings.
                safe_headers = {
                    k: v
                    for k, v in response.headers.items()
                    if k
                    not in ("content-encoding", "content-length", "transfer-encoding", "connection")
                }
                return HTTPResult(
                    str(response.url), response.status_code, safe_headers, body, cookies
                )
    raise FetchError("redirect limit exceeded")


def require_html(result: HTTPResult) -> None:
    if not 200 <= result.status < 300:
        raise FetchError(f"source returned HTTP {result.status}")
    content_type = result.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ("text/html", "application/xhtml+xml", "text/plain"):
        raise FetchError("source is not HTML or plain text")


async def _fetch_static(url: str, s: Settings, allowed_host: str | None = None) -> FetchResult:
    result = await request_http(url, s, allowed_host=allowed_host)
    require_html(result)
    return FetchResult(result.url, result.status, result.text(), "static")


async def _fetch_browser(
    url: str, s: Settings, pool: BrowserPool, allowed_host: str | None = None
) -> FetchResult:
    async with pool.page() as page:
        await pool.navigate(page, url, allowed_host=allowed_host)
        # Wait for delayed JS content, within a fixed readiness budget. Short pages
        # are still valid when the timeout expires; no unbounded network-idle wait.
        try:
            await page.wait_for_function(
                "document.body && document.body.innerText.trim().length >= 200",
                timeout=s.browser_ready_timeout_s * 1000,
            )
        except Exception as exc:
            from playwright.async_api import TimeoutError as PlaywrightTimeout

            if not isinstance(exc, PlaywrightTimeout):
                raise
        state = pool.page_state(page)
        if state.error:
            raise FetchError(state.error)
        # Check size inside the renderer before allocating/returning a serialized DOM.
        html = await page.evaluate(
            """maximum => {
            const html = document.documentElement.outerHTML;
            if (new TextEncoder().encode(html).byteLength > maximum) return null;
            return html;
        }""",
            s.max_response_bytes,
        )
        if html is None:
            raise FetchError("rendered document exceeds byte limit")
        return FetchResult(state.final_url or page.url, 200, html, "browser")


def _looks_gated(html: str) -> bool:
    import trafilatura

    return len((trafilatura.extract(html) or "").strip()) < 200


async def fetch(
    url: str,
    *,
    render: bool,
    settings: Settings,
    pool: BrowserPool,
    allowed_host: str | None = None,
) -> FetchResult:
    parse_url(url)
    async with pool.fetch_slots.slot(), asyncio.timeout(settings.request_timeout_s):
        if render:
            return await _fetch_browser(url, settings, pool, allowed_host)
        result = await _fetch_static(url, settings, allowed_host)
        if settings.browser_enabled and await work.run(_looks_gated, result.html):
            return await _fetch_browser(result.url, settings, pool, allowed_host)
        return result
