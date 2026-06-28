"""scrape — fetch one URL and return clean markdown."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import extract_links, title_of, to_markdown
from ..runtime import pool


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def scrape(
        url: Annotated[str, Field(description="The URL to scrape (http/https).")],
        render: Annotated[
            bool, Field(description="Force a headless browser render (for JS-heavy pages).")
        ] = False,
        include_links: Annotated[
            bool, Field(description="Also return all links found on the page.")
        ] = False,
        include_raw_html: Annotated[
            bool, Field(description="Also return the raw HTML (large).")
        ] = False,
    ) -> dict:
        """Scrape a single URL into clean markdown (boilerplate/ads stripped).

        Tries a fast static fetch first and falls back to a stealth headless
        browser automatically when the page looks JS-gated.
        """
        result = await fetch(url, render=render, settings=settings, pool=pool)
        out: dict = {
            "url": result.url,
            "status": result.status,
            "via": result.via,
            "title": title_of(result.html),
            "markdown": to_markdown(result.html, result.url),
        }
        if include_links:
            out["links"] = extract_links(result.html, result.url)
        if include_raw_html:
            out["html"] = result.html
        return out
