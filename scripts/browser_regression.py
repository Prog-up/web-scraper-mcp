"""Offline browser/proxy regressions for the exact shipped sandboxed container.

Run inside the built image with --network none, the approved seccomp profile,
non-root execution, SYS_CHROOT-only capabilities, no-new-privileges,
read-only storage, and resource caps.
The localhost origin is fulfilled by a fake broker to make it a secure context;
no external site is contacted. Private endpoints are real local logging sockets.
"""

import asyncio
import json

from web_scraper_mcp import fetch as fetching
from web_scraper_mcp.browser import BrowserPool
from web_scraper_mcp.config import Settings
from web_scraper_mcp.egress import EgressProxy
from web_scraper_mcp.fetch import HTTPResult, _fetch_browser
from web_scraper_mcp.security import BlockedURLError


async def main():
    settings = Settings(
        _env_file=None,
        browser_enabled=True,
        egress_proxy_url="http://127.0.0.1:9",
        respect_robots=False,
    )
    pool = BrowserPool(settings)
    private_hits = []

    async def denied(reader, writer):
        private_hits.append(await reader.read(1024))
        writer.close()
        await writer.wait_closed()

    fixture = await asyncio.start_server(denied, "127.0.0.1", 0)
    port = fixture.sockets[0].getsockname()[1]
    blocked = []
    html = f"""<html><head><title>Delayed fixture</title></head>
    <body><main id="content">Loading</main>
    <script>
    window.wsOpen=false;
    window.swBlocked=false;
    let ws=new WebSocket('ws://127.0.0.1:{port}/private');
    ws.onopen=()=>window.wsOpen=true;
    navigator.serviceWorker.register('/worker.js').catch(()=>window.swBlocked=true);
    fetch('http://127.0.0.1:{port}/private').catch(()=>{{}});
    setTimeout(()=> {{
      document.getElementById('content').textContent='Delayed public article content. '.repeat(20);
    }},150);
    </script></body></html>""".encode()

    async def broker(url, settings, **kwargs):
        if "127.0.0.1" in url:
            blocked.append(url)
            raise BlockedURLError("private fixture")
        assert url.startswith("http://fixture.localhost/")
        return HTTPResult(
            "http://fixture.localhost/final/", 200, {"content-type": "text/html"}, html
        )

    fetching.request_http = broker
    try:
        result = await _fetch_browser("http://fixture.localhost/start", settings, pool)
        assert "Delayed public article content." in result.html
        assert result.url == "http://fixture.localhost/final/"
        assert blocked, "private HTTP resource was not intercepted"
        assert not private_hits, "browser bypassed broker/WebSocket denial"
        async with pool.page() as page:
            await page.goto("http://fixture.localhost/start", wait_until="domcontentloaded")
            await page.wait_for_function("document.body.innerText.length >= 200", timeout=3000)
            registrations = await page.evaluate(
                "navigator.serviceWorker.getRegistrations().then(items => items.length)"
            )
            assert registrations == 0
            assert await page.evaluate("window.wsOpen") is False
        # Test the actual socket proxy separately, including private HTTPS CONNECT.
        proxy = EgressProxy(settings)
        server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        async with server:
            proxy_port = server.sockets[0].getsockname()[1]
            for target in ["GET http://127.0.0.1/", "CONNECT 127.0.0.1:443"]:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
                writer.write((target + " HTTP/1.1\r\nHost: denied\r\n\r\n").encode())
                await writer.drain()
                assert (await reader.read(1024)).startswith(b"HTTP/1.1 403")
                writer.close()
                await writer.wait_closed()
        print(
            json.dumps(
                {
                    "sandbox": True,
                    "delayed_dom": True,
                    "redirect_final_url": True,
                    "private_http_intercepted": True,
                    "websocket_blocked": True,
                    "service_worker_blocked": True,
                    "denied_fixture_hits": len(private_hits),
                    "live_proxy_http_connect_denied": True,
                }
            )
        )
    finally:
        fixture.close()
        await fixture.wait_closed()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=30))
