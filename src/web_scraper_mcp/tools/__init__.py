"""MCP tool registration. Each submodule adds one tool family to the server."""

from __future__ import annotations

from fastmcp import FastMCP

from . import crawl, extract, interact, map, research, scrape, search


def register(mcp: FastMCP) -> None:
    scrape.register(mcp)
    crawl.register(mcp)
    map.register(mcp)
    extract.register(mcp)
    search.register(mcp)
    interact.register(mcp)
    research.register(mcp)
