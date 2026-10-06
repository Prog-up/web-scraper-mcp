"""Connection-time enforcement retains HTTP authority and TLS identity."""

import asyncio
import socket

import httpcore
import httpx
import pytest

from web_scraper_mcp import security, transport
from web_scraper_mcp.security import BlockedURLError


async def test_backend_connects_only_approved_ip_once(monkeypatch):
    resolutions = []
    connections = []

    async def resolve(host, port, **kwargs):
        resolutions.append((host, port))
        return ["1.1.1.1"] if len(resolutions) == 1 else ["127.0.0.1"]

    class Backend:
        async def connect_tcp(self, host, port, *args):
            connections.append((host, port))
            return httpcore.AsyncMockStream([])

    monkeypatch.setattr(transport, "resolve_host", resolve)
    backend = transport.PublicNetworkBackend()
    backend.backend = Backend()
    await backend.connect_tcp("rebind.example", 443)
    assert resolutions == [("rebind.example", 443)]
    assert connections == [("1.1.1.1", 443)]


async def test_mixed_dns_answer_denied_before_dial(monkeypatch):
    async def dns(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", dns)
    with pytest.raises(BlockedURLError):
        await transport.PublicNetworkBackend().connect_tcp("mixed.example", 80)


async def test_https_keeps_host_sni_and_certificate_checks(monkeypatch):
    writes = []
    tls = []

    class Stream(httpcore.AsyncMockStream):
        async def write(self, data, timeout=None):  # noqa: ASYNC109 - HTTPcore interface
            writes.append(data)

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):  # noqa: ASYNC109
            tls.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
            return self

    class Backend:
        async def connect_tcp(self, host, port, *args):
            assert host == "1.1.1.1"
            return Stream([b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"])

    async def resolve(*args, **kwargs):
        return ["1.1.1.1"]

    monkeypatch.setattr(transport, "resolve_host", resolve)
    adapter = transport.PublicTransport()
    adapter.pool = httpcore.AsyncConnectionPool(
        ssl_context=httpcore.default_ssl_context(), network_backend=transport.PublicNetworkBackend()
    )
    adapter.pool._network_backend.backend = Backend()
    async with httpx.AsyncClient(transport=adapter, trust_env=False) as client:
        response = await client.get("https://original.example/")
    assert response.text == "ok"
    assert b"Host: original.example" in b"".join(writes)
    assert tls[0][0] == "original.example"
    assert tls[0][1] is True
    assert tls[0][2] == __import__("ssl").CERT_REQUIRED


@pytest.mark.parametrize(
    "url",
    [
        "http://100.64.0.1/",
        "http://100.100.100.200/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost./",
        "http://user:password@1.1.1.1/",
        "http://1.1.1.1:0/",
        "http://1.1.1.1:99999/",
        "http://1.1.1.1/\nheader",
        "http://1.1.1.1\\@127.0.0.1/",
    ],
)
def test_non_global_and_ambiguous_urls_are_rejected(url):
    with pytest.raises(BlockedURLError):
        security.validate_url(url)


async def test_slow_resolver_does_not_block_event_loop(monkeypatch):
    event = asyncio.Event()

    async def dns(*args, **kwargs):
        await event.wait()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 80))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    task = asyncio.create_task(security.resolve_host("slow.example", 80))
    await asyncio.sleep(0)
    assert not task.done()
    event.set()
    assert await task == ["1.1.1.1"]


async def test_cancelled_dns_waiter_retains_resolution_capacity(monkeypatch):
    from web_scraper_mcp.limits import CapacityError

    entered = asyncio.Event()
    finish = asyncio.Event()

    async def dns(*args, **kwargs):
        entered.set()
        await finish.wait()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 80))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    monkeypatch.setattr(security, "_DNS_MAXIMUM", 1)
    task = asyncio.create_task(security.resolve_host("slow.example", 80))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(CapacityError):
        await security.resolve_host("second.example", 80)
    finish.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert security._dns_active == 0
