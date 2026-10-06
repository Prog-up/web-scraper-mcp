"""scrape — fetch one URL and return clean markdown."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import extract_links, title_of, to_markdown
from ..runtime import pool
from ..work import work


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def scrape(
        url: Annotated[str, Field(max_length=8192, description="The URL to scrape (http/https).")],
        render: Annotated[
            bool, Field(description="Force a headless browser render (for JS-heavy pages).")
        ] = False,
        include_links: Annotated[
            bool, Field(description="Return up to 1,000 links, at most 256 KB total.")
        ] = False,
        include_raw_html: Annotated[
            bool, Field(description="Also return the raw HTML (large).")
        ] = False,
    ) -> dict:
        """Scrape a public URL into main-content markdown with optional links.

        Fetches static HTML first. If rendering is explicitly enabled, sparse
        pages can fall back to the isolated, sandboxed browser.
        """
        result = await fetch(url, render=render, settings=settings, pool=pool)
        out: dict = {
            "url": result.url,
            "status": result.status,
            "via": result.via,
            "title": await work.run(title_of, result.html),
            "markdown": await work.run(to_markdown, result.html, result.url),
        }
        if include_links:
            out["links"] = await work.run(extract_links, result.html, result.url)
        if include_raw_html:
            out["html"] = result.html
        return out
