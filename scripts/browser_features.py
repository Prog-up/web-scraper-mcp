"""Registered browser tool regressions in the bounded sandbox test container."""

import asyncio
import json
import socket
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from web_scraper_mcp import fetch as fetching
from web_scraper_mcp import server
from web_scraper_mcp.browser import BrowserPool
from web_scraper_mcp.config import Settings
from web_scraper_mcp.fetch import HTTPResult
from web_scraper_mcp.security import BlockedURLError
from web_scraper_mcp.tools import interact

FORM = b"""<html><head><title>Interactive fixture</title></head><body>
<form action="/submit" method="post"><label>Name<input id="name" name="name"></label>
<select id="choice" name="choice"><option value="one">One</option>
<option value="two">Two</option></select>
<button id="submit" type="submit">Submit</button></form>
<button id="spa" type="button" onclick="history.pushState({},'','/spa')">SPA route</button>
<button id="cross" onclick="fetch('http://other.example/capture',{method:'POST',body:'blocked'})
.catch(()=>document.getElementById('cross-state').hidden=false)">Cross origin</button>
<div id="cross-state" hidden>Cross origin blocked</div>
<script>fetch('/unprompted', {method:'POST',body:'blocked'}).catch(()=>{});</script>
</body></html>"""


@asynccontextmanager
async def connected_client(app, transport):
    if transport == "inprocess":
        async with Client(app) as client:
            yield client
        return
    ready = asyncio.Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            ready.set()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = Server(uvicorn.Config(app.http_app(), log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            await ready.wait()
        http = StreamableHttpTransport(
            f"http://127.0.0.1:{port}/mcp",
            headers={"Authorization": "Bearer fixture-browser-token"},
        )
        async with Client(http) as client:
            yield client
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


async def main(transport="inprocess"):
    settings = Settings(
        _env_file=None,
        transport="http" if transport == "http" else "stdio",
        auth_token="fixture-browser-token" if transport == "http" else None,
        browser_enabled=True,
        egress_proxy_url="http://127.0.0.1:9",
        respect_robots=False,
    )
    pool = BrowserPool(settings)
    interact.settings = settings
    interact.pool = pool
    server.pool = pool
    requests = []

    async def broker(url, settings, **kwargs):
        if not url.startswith("http://fixture.localhost/"):
            raise BlockedURLError("unexpected destination")
        method = kwargs.get("method", "GET")
        requests.append(
            {
                "url": url,
                "method": method,
                "headers": kwargs.get("headers", {}),
                "content": kwargs.get("content"),
            }
        )
        if urlsplit(url).path == "/submit":
            assert method == "POST"
            assert b"name=Alice" in kwargs["content"] and b"choice=two" in kwargs["content"]
            assert "session=one" in kwargs["headers"].get("cookie", "")
            assert "csrf=two" in kwargs["headers"].get("cookie", "")
            return HTTPResult(
                "http://fixture.localhost/submitted",
                200,
                {"content-type": "text/html"},
                b"<html><head><title>Submitted</title></head>"
                b"<body>Submitted successfully</body></html>",
            )
        if "/submitted" in url:
            return HTTPResult(
                url,
                200,
                {"content-type": "text/html"},
                b"<html><head><title>Submitted</title></head>"
                b"<body>Submitted successfully</body></html>",
            )
        return HTTPResult(
            url,
            200,
            {"content-type": "text/html"},
            FORM,
            [
                (url, "session=one; Path=/; HttpOnly; SameSite=Lax"),
                (url, "csrf=two; Path=/; SameSite=Lax"),
            ],
        )

    fetching.request_http = broker
    async with connected_client(server.build_app(settings), transport) as client:
        inventory = {tool.name for tool in await client.list_tools()}
        assert len(inventory) == 10
        first = (
            await client.call_tool(
                "browser_navigate", {"url": "http://fixture.localhost/form?first"}
            )
        ).data
        sid = first["session_id"]
        assert first["title"] == "Interactive fixture" and "Submit" in first["snapshot"]
        assert pool._slots.active == 1
        assert not await interact._sessions[sid].page.evaluate("navigator.webdriver")
        await client.call_tool(
            "browser_act",
            {"session_id": sid, "action": "fill", "selector": "#name", "value": "Alice"},
        )
        await client.call_tool(
            "browser_act",
            {"session_id": sid, "action": "press", "selector": "#name", "value": "End"},
        )
        await client.call_tool(
            "browser_act",
            {"session_id": sid, "action": "select", "selector": "#choice", "value": "two"},
        )
        await client.call_tool(
            "browser_act", {"session_id": sid, "action": "wait", "selector": "#submit"}
        )
        spa = (
            await client.call_tool(
                "browser_act", {"session_id": sid, "action": "click", "selector": "#spa"}
            )
        ).data
        assert spa["url"] == "http://fixture.localhost/spa"
        assert await interact._sessions[sid].page.input_value("#name") == "Alice"
        await client.call_tool(
            "browser_act", {"session_id": sid, "action": "click", "selector": "#cross"}
        )
        await client.call_tool(
            "browser_act", {"session_id": sid, "action": "wait", "selector": "#cross-state"}
        )
        assert not any(
            "other.example" in item["url"] or "/unprompted" in item["url"] for item in requests
        )
        submitted = (
            await client.call_tool(
                "browser_act", {"session_id": sid, "action": "click", "selector": "#submit"}
            )
        ).data
        assert submitted.get("title") == "Submitted", submitted
        assert submitted["url"] == "http://fixture.localhost/submitted"
        assert "Submitted successfully" in submitted["snapshot"]
        reused = (
            await client.call_tool(
                "browser_navigate",
                {"url": "http://fixture.localhost/form?reuse", "session_id": sid},
            )
        ).data
        assert reused["session_id"] == sid
        assert (
            "session=one" in next(r for r in requests if "?reuse" in r["url"])["headers"]["cookie"]
        )
        second = (
            await client.call_tool(
                "browser_navigate", {"url": "http://fixture.localhost/form?second"}
            )
        ).data
        assert "cookie" not in next(r for r in requests if "?second" in r["url"])["headers"]
        denied = await client.call_tool(
            "browser_navigate", {"url": "http://fixture.localhost/form?third"}, raise_on_error=False
        )
        assert denied.is_error and pool._slots.active == 2
        await client.call_tool("browser_close", {"session_id": sid})
        assert pool._slots.active == 1
        sid2 = second["session_id"]
        interact._sessions[sid2].expires_at = time.monotonic() - 1
        expired = (
            await client.call_tool(
                "browser_navigate", {"url": "http://fixture.localhost/form", "session_id": sid2}
            )
        ).data
        assert "error" in expired and pool._slots.active == 0
        failed = await client.call_tool(
            "browser_navigate", {"url": "http://127.0.0.1/private"}, raise_on_error=False
        )
        assert failed.is_error and pool._slots.active == 0
        assert len(pool._browser.contexts) == 0
        # Unclosed sessions must also release their capacity on server shutdown.
        await client.call_tool(
            "browser_navigate", {"url": "http://fixture.localhost/form?shutdown"}
        )
        assert pool._slots.active == 1
    assert pool._slots.active == 0 and not interact._sessions
    print(
        json.dumps(
            {
                "transport": transport,
                "tool_count": len(inventory),
                "navigate_reuse_close": True,
                "fill_press_select_wait_click": True,
                "same_origin_form_post": True,
                "spa_history_preserves_form": True,
                "multiple_cookie_roundtrip": True,
                "cross_origin_and_idle_posts_denied": True,
                "session_isolation": True,
                "stealth_webdriver_mask": True,
                "session_admission_expiry_shutdown": True,
                "private_navigation_cleanup": True,
            }
        )
    )


if __name__ == "__main__":

    async def both():
        await main()
        await main("http")

    asyncio.run(asyncio.wait_for(both(), timeout=60))
