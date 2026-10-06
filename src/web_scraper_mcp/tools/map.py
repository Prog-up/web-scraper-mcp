"""Discover bounded links through the shared safe fetch/parser layer."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import extract_links
from ..runtime import pool
from ..work import work


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def map(
        url: Annotated[str, Field(max_length=8192, description="Page to discover links from.")],
        limit: Annotated[int, Field(ge=1, le=2000, description="Maximum links.")] = 200,
        same_domain: bool = True,
    ) -> dict:
        """List a page's URLs, optionally restricting normalized host and port."""
        result = await fetch(url, render=False, settings=settings, pool=pool)

        def links():
            return extract_links(result.html, result.url, same_domain=same_domain, limit=limit)

        found = await work.run(links)
        return {"url": result.url, "count": len(found), "links": found}
