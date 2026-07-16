"""FastMCP app + entrypoint.

Runs as an HTTP service by default (containerized), bound to settings.host.
A shared bearer token (SCRAPER_AUTH_TOKEN) protects the endpoint; if unset the
endpoint is unauthenticated and a warning is logged — only fine for local stdio.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from .config import settings
from .runtime import pool
from .tools import register

logging.basicConfig(level=os.environ.get("SCRAPER_LOG_LEVEL", "INFO"))
logger = logging.getLogger("web_scraper_mcp")


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    try:
        yield
    finally:
        logger.info("Closing browser pool...")
        await pool.close()


def build_app() -> FastMCP:
    auth = None
    if settings.auth_token:
        auth = StaticTokenVerifier(
            tokens={settings.auth_token: {"client_id": "local", "scopes": ["scrape"]}}
        )
    else:
        logger.warning(
            "SCRAPER_AUTH_TOKEN is not set — the HTTP endpoint is UNAUTHENTICATED. "
            "Set a token for any networked deployment."
        )
    mcp = FastMCP("web-scraper-mcp", auth=auth, lifespan=server_lifespan)

    register(mcp)
    return mcp


app = build_app()


def main() -> None:
    """Console entrypoint. Transport via SCRAPER_TRANSPORT (default: http)."""
    transport = os.environ.get("SCRAPER_TRANSPORT", "http")
    if transport == "stdio":
        app.run(transport="stdio")
    else:
        app.run(transport="http", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
