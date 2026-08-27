"""MCP tool registration. Each submodule adds one tool family to the server."""

from __future__ import annotations

from fastmcp import FastMCP

from . import extract, research, scrape, search


def register(mcp: FastMCP) -> None:
    scrape.register(mcp)
    extract.register(mcp)
    search.register(mcp)
    research.register(mcp)
