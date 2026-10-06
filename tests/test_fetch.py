"""Regression fixtures for byte limits, redirects, robots, status and deadlines."""

import asyncio
import gzip

import httpx
import pytest

from web_scraper_mcp import fetch as fm
from web_scraper_mcp.browser import BrowserPool
from web_scraper_mcp.config import Settings
from web_scraper_mcp.security import BlockedURLError


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.read += len(chunk)
            yield chunk

    async def aclose(self):
        self.closed = True


def config(**kwargs):
    defaults = {"per_domain_delay_s": 0, "respect_robots": False}
    defaults.update(kwargs)
    return Settings(_env_file=None, **defaults)


def client_fixture(monkeypatch, handler):
    monkeypatch.setattr(
        fm,
        "public_client",
        lambda s: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )


async def test_oversize_stream_aborts_and_closes(monkeypatch):
    stream = Chunks([b"x" * 512] * 100)
    client_fixture(
        monkeypatch,
        lambda r: httpx.Response(200, stream=stream, headers={"content-type": "text/html"}),
    )
    with pytest.raises(fm.FetchError, match="byte limit"):
        await fm._fetch_static("https://limit.example/", config(max_response_bytes=1024))
    assert stream.read < 20_000
    assert stream.closed


async def test_gzip_bomb_has_bounded_decoded_output(monkeypatch):
    stream = Chunks([gzip.compress(b"x" * 100_000)])
    client_fixture(
        monkeypatch,
        lambda r: httpx.Response(
            200, stream=stream, headers={"content-type": "text/html", "content-encoding": "gzip"}
        ),
    )
    with pytest.raises(fm.FetchError, match="decoded byte limit"):
        await fm._fetch_static("https://gzip.example/", config(max_response_bytes=1024))
    assert stream.closed


async def test_multibyte_cap_is_bytes(monkeypatch):
    client_fixture(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            stream=Chunks(["é".encode() * 600]),
            headers={"content-type": "text/html; charset=utf-8"},
        ),
    )
    with pytest.raises(fm.FetchError, match="byte limit"):
        await fm._fetch_static("https://unicode.example/", config(max_response_bytes=1024))


async def test_redirect_checks_destination_robots_and_strips_credentials(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.host == "first.example":
            return httpx.Response(302, headers={"location": "https://second.example/page"})
        return httpx.Response(200, text="article", headers={"content-type": "text/html"})

    client_fixture(monkeypatch, handler)
    fm._robots_cache.clear()
    await fm.request_http(
        "https://first.example/page",
        config(respect_robots=True),
        headers={"authorization": "Bearer test-token", "cookie": "test=value"},
    )
    assert any(r.url.host == "second.example" and r.url.path == "/robots.txt" for r in requests)
    destination = next(
        r for r in requests if r.url.host == "second.example" and r.url.path == "/page"
    )
    assert "authorization" not in destination.headers
    assert "cookie" not in destination.headers


@pytest.mark.parametrize("status", [403, 429, 500])
async def test_robots_fails_closed(monkeypatch, status):
    fm._robots_cache.clear()
    client_fixture(monkeypatch, lambda r: httpx.Response(status))
    with pytest.raises(BlockedURLError):
        await fm._fetch_static("https://robots.example/page", config(respect_robots=True))


async def test_http_error_does_not_render_or_become_source(monkeypatch):
    s = config(browser_enabled=True)
    client_fixture(monkeypatch, lambda r: httpx.Response(404, text="not found"))
    with pytest.raises(fm.FetchError, match="HTTP 404"):
        await fm.fetch("https://error.example/", render=False, settings=s, pool=BrowserPool(s))


async def test_total_download_deadline(monkeypatch):
    stream = Chunks([b"x"] * 100, delay=0.01)
    client_fixture(
        monkeypatch,
        lambda r: httpx.Response(200, stream=stream, headers={"content-type": "text/html"}),
    )
    with pytest.raises(TimeoutError):
        await fm._fetch_static("https://slow.example/", config(request_timeout_s=0.03))
    assert stream.closed


async def test_domain_and_robots_caches_are_bounded(monkeypatch):
    fm._domain_states.clear()
    fm._robots_cache.clear()
    client_fixture(monkeypatch, lambda r: httpx.Response(404))
    s = config(cache_entries=2)
    for i in range(6):
        await fm._robots_for(f"https://site-{i}.example/", s)
    assert len(fm._domain_states) <= 2
    assert len(fm._robots_cache) <= 2


async def test_same_host_crawl_rejects_redirect_before_following(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://other.example/"})

    client_fixture(monkeypatch, handler)
    with pytest.raises(BlockedURLError, match="permitted host"):
        await fm.request_http(
            "https://seed.example/", config(), allowed_host="https://seed.example/"
        )
    assert len(requests) == 1 and requests[0].url.host == "seed.example"


@pytest.mark.parametrize("status", [302, 303, 307, 308])
async def test_action_post_redirect_method_and_cookie_roundtrip(monkeypatch, status):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/form":
            return httpx.Response(
                status,
                headers=[
                    ("location", "/success"),
                    ("set-cookie", "session=one; Path=/"),
                    ("set-cookie", "csrf=two; Path=/"),
                ],
            )
        return httpx.Response(200, text="done")

    client_fixture(monkeypatch, handler)
    result = await fm.request_http(
        "https://forms.example/form",
        config(),
        method="POST",
        content=b"name=test",
        write_origin=fm.origin("https://forms.example/"),
    )
    assert requests[1].method == ("GET" if status in (302, 303) else "POST")
    assert requests[1].content == (b"" if status in (302, 303) else b"name=test")
    assert "session=one" in requests[1].headers["cookie"]
    assert len(result.cookies) == 2


async def test_post_cannot_carry_body_across_origin_redirect(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"location": "https://other.example/steal"})

    client_fixture(monkeypatch, handler)
    with pytest.raises(BlockedURLError, match="authorized origin"):
        await fm.request_http(
            "https://forms.example/submit",
            config(),
            method="POST",
            content=b"credential=test",
            write_origin=fm.origin("https://forms.example/"),
        )
    assert len(requests) == 1
