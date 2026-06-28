"""search — pluggable web search.

Backend chosen by which env is set (first wins): Tavily, Brave, SearXNG, else
DuckDuckGo (ddgs, no key). All return the same shape so the tool signature never
changes. ponytail: one tool, no per-provider tool explosion.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import httpx
from fastmcp import FastMCP
from pydantic import Field

from ..config import settings


async def _ddgs(query: str, n: int) -> list[dict]:
    from ddgs import DDGS

    def run() -> list[dict]:
        rows = DDGS().text(query, max_results=n)
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
            for r in rows
        ]

    return await asyncio.to_thread(run)


async def _searxng(query: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        resp = await client.get(
            f"{settings.searxng_url.rstrip('/')}/search",  # type: ignore[union-attr]
            params={"q": query, "format": "json"},
        )
        resp.raise_for_status()
        rows = resp.json().get("results", [])[:n]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in rows
    ]


async def _brave(query: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": n},
            headers={"X-Subscription-Token": settings.brave_api_key or ""},
        )
        resp.raise_for_status()
        rows = resp.json().get("web", {}).get("results", [])[:n]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("description", "")}
        for r in rows
    ]


async def _tavily(query: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": settings.tavily_api_key, "query": query, "max_results": n},
        )
        resp.raise_for_status()
        rows = resp.json().get("results", [])[:n]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in rows
    ]


def _pick_backend() -> tuple[str, object]:
    if settings.tavily_api_key:
        return "tavily", _tavily
    if settings.brave_api_key:
        return "brave", _brave
    if settings.searxng_url:
        return "searxng", _searxng
    return "duckduckgo", _ddgs


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def search(
        query: Annotated[str, Field(description="Search query.")],
        max_results: Annotated[int, Field(description="Max results.", ge=1, le=50)] = 10,
    ) -> dict:
        """Web search. Returns ranked results (title, url, content snippet)."""
        backend, fn = _pick_backend()
        try:
            results = await fn(query, max_results)  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001
            return {"backend": backend, "error": str(exc), "results": []}
        return {"backend": backend, "count": len(results), "results": results}
