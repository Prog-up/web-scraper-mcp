"""search — pluggable web search.

Backend chosen by which env is set (first wins): Tavily, Brave, SearXNG, else
DuckDuckGo (ddgs, no key). All return the same shape so the tool signature never
changes. ponytail: one tool, no per-provider tool explosion.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated

import httpx
from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import read_body
from ..work import work


async def _ddgs(query: str, n: int) -> list[dict]:
    from ddgs import DDGS

    def run() -> list[dict]:
        with DDGS(
            proxy=settings.egress_proxy_url, timeout=max(1, int(settings.request_timeout_s))
        ) as client:
            rows = client.text(query, max_results=n)
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
            for r in rows
        ]

    async with asyncio.timeout(settings.request_timeout_s):
        return await work.run(run)


async def _provider_request(method: str, url: str, **kwargs) -> dict:
    async with (
        asyncio.timeout(settings.request_timeout_s),
        httpx.AsyncClient(
            timeout=settings.request_timeout_s,
            trust_env=False,
            proxy=settings.egress_proxy_url,
            follow_redirects=False,
        ) as client,
    ):
        async with client.stream(method, url, **kwargs) as response:
            response.raise_for_status()
            return json.loads(await read_body(response, settings.max_response_bytes))


async def _searxng(query: str, n: int) -> list[dict]:
    data = await _provider_request(
        "GET",
        f"{settings.searxng_url.rstrip('/')}/search",  # type: ignore[union-attr]
        params={"q": query, "format": "json"},
    )
    rows = data.get("results", [])[:n]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in rows
    ]


async def _brave(query: str, n: int) -> list[dict]:
    data = await _provider_request(
        "GET",
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": n},
        headers={"X-Subscription-Token": settings.brave_api_key or ""},
    )
    rows = data.get("web", {}).get("results", [])[:n]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("description", "")}
        for r in rows
    ]


async def _tavily(query: str, n: int) -> list[dict]:
    data = await _provider_request(
        "POST",
        "https://api.tavily.com/search",
        json={"api_key": settings.tavily_api_key, "query": query, "max_results": n},
    )
    rows = data.get("results", [])[:n]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in rows
    ]


def _pick_backend() -> tuple[str, Callable[[str, int], Awaitable[list[dict]]]]:
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
        query: Annotated[str, Field(min_length=1, max_length=2048, description="Search query.")],
        max_results: Annotated[int, Field(description="Max results.", ge=1, le=50)] = 10,
    ) -> dict:
        """Web search. Returns ranked results (title, url, content snippet)."""
        backend, fn = _pick_backend()
        try:
            results = await fn(query, max_results)
        except Exception:
            return {"backend": backend, "error": "search provider was unavailable", "results": []}
        return {"backend": backend, "count": len(results), "results": results}
