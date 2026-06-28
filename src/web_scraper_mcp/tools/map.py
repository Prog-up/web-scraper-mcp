"""map — discover URLs on a page (cheap, one fetch)."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import extract_links
from ..runtime import pool


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def map(
        url: Annotated[str, Field(description="Page to discover links from.")],
        limit: Annotated[int, Field(description="Max links to return.", ge=1, le=2000)] = 200,
        same_domain: Annotated[
            bool, Field(description="Only return links on the same host.")
        ] = True,
    ) -> dict:
        """List the URLs found on a page — useful to decide what to crawl/scrape."""
        result = await fetch(url, render=False, settings=settings, pool=pool)
        links = extract_links(result.html, result.url, same_domain=same_domain)[:limit]
        return {"url": result.url, "count": len(links), "links": links}
