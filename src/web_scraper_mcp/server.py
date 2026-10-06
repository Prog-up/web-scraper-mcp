"""Authenticated MCP entrypoint with bounded input and tool admission."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.middleware import Middleware

from .config import Settings, settings
from .limits import Limiter
from .runtime import pool
from .tools import crawl, interact, register

logger = logging.getLogger(__name__)


class ToolLimits(Middleware):
    def __init__(self, config: Settings):
        self.config = config
        self.slots = Limiter(config.max_concurrent_tools)

    async def on_call_tool(self, context, call_next):
        if len(json.dumps(context.message.arguments).encode()) > self.config.max_request_bytes:
            raise ValueError("tool arguments exceed request limit")
        async with self.slots.slot(), asyncio.timeout(self.config.tool_timeout_s):
            return await call_next(context)


class BodyLimit:
    """Cap HTTP bodies before JSON parsing, even without a Content-Length header."""

    def __init__(self, app, maximum: int):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        async with asyncio.timeout(10):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.maximum:
                    await send({"type": "http.response.start", "status": 413, "headers": []})
                    await send(
                        {"type": "http.response.body", "body": b"request exceeds byte limit"}
                    )
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    crawl.start_cleanup()
    interact.start_cleanup()
    try:
        yield
    finally:
        await crawl.close()
        await interact.close()
        await pool.close()


def build_app(config: Settings | None = None) -> FastMCP:
    config = config or settings
    token = config.auth_token
    if config.transport == "http" and (not token or not token.strip()):
        raise ValueError("SCRAPER_AUTH_TOKEN is required for HTTP; use stdio for token-free access")
    auth = None
    if config.transport == "http":
        auth = StaticTokenVerifier(
            tokens={str(token): {"client_id": "local", "scopes": ["scrape"]}}
        )
    mcp = FastMCP(
        "web-scraper-mcp",
        auth=auth,
        lifespan=server_lifespan,
        middleware=[ToolLimits(config)],
        mask_error_details=True,
    )
    register(mcp)
    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp = build_app()
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn
        from starlette.middleware import Middleware as ASGIMiddleware

        app = mcp.http_app(
            middleware=[ASGIMiddleware(BodyLimit, maximum=settings.max_request_bytes)]
        )
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            limit_concurrency=32,
            timeout_keep_alive=5,
            access_log=False,
        )


if __name__ == "__main__":
    main()
