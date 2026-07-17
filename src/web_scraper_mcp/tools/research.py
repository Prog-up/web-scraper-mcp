"""deep_research — search, scrape the top sources, synthesize a cited report.

Composes search + fetch + an Anthropic synthesis pass. Needs ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import title_of, to_markdown
from ..runtime import pool
from .search import _pick_backend

# Per-source budget fed to the model. ponytail: fixed char cap, tune if needed.
_PER_SOURCE_CHARS = 8_000


async def _grab(url: str) -> dict | None:
    try:
        result = await fetch(url, render=False, settings=settings, pool=pool)
    except Exception:  # noqa: BLE001 - skip unreachable/blocked sources
        return None
    return {
        "url": result.url,
        "title": title_of(result.html),
        "markdown": to_markdown(result.html, result.url),
    }


async def _synthesize(query: str, docs: list[dict]) -> str:
    model = settings.research_model
    blob = "\n\n".join(
        f"## Source {i + 1}: {d['url']}\n{d['markdown'][:_PER_SOURCE_CHARS]}"
        for i, d in enumerate(docs)
    )
    system = (
        "You are a research assistant. Synthesize the provided sources into a "
        "concise, structured report that answers the question. Cite sources "
        "inline as [n] using the source numbers."
    )

    if model.startswith("claude-"):
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": f"Question: {query}\n\nSources:\n{blob}"}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    # Ollama execution path
    import httpx

    url = settings.ollama_url("/api/chat")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Question: {query}\n\nSources:\n{blob}"},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as http_client:
        resp = await http_client.post(url, json=payload)

        resp.raise_for_status()
        data = resp.json()
    return data.get("message", {}).get("content", "")


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def deep_research(
        query: Annotated[str, Field(description="The research question.")],
        max_sources: Annotated[
            int, Field(description="How many top results to read.", ge=1, le=15)
        ] = 5,
    ) -> dict:
        """Search the web, read the top sources, and return a cited synthesis report."""
        if settings.research_model.startswith("claude-") and not settings.anthropic_api_key:
            return {"error": "ANTHROPIC_API_KEY is not set — deep_research is unavailable."}
        backend, fn = _pick_backend()
        try:
            hits = await fn(query, max_sources)  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001
            return {"error": f"search failed: {exc}"}
        grabbed = await asyncio.gather(*(_grab(h["url"]) for h in hits if h.get("url")))
        docs = [d for d in grabbed if d]
        if not docs:
            return {"error": "no sources could be read", "backend": backend}
        report = await _synthesize(query, docs)
        return {
            "query": query,
            "backend": backend,
            "sources": [{"url": d["url"], "title": d["title"]} for d in docs],
            "report": report,
        }
