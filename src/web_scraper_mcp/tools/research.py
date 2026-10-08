"""Search/read bounded sources, synthesize, and validate source citation indices."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..llm import (
    UNTRUSTED_SYSTEM,
    input_budget,
    model_slots,
    ollama_chat,
    provider_for,
    truncate_bytes,
)
from ..parse import title_of, to_markdown
from ..runtime import pool
from ..work import work
from .extract import httpx_client
from .search import _pick_backend


async def _grab(url: str) -> dict:
    try:
        result = await fetch(url, render=False, settings=settings, pool=pool)
        markdown = await work.run(to_markdown, result.html, result.url)
        title = await work.run(title_of, result.html)
        return {"url": result.url, "title": title, "markdown": markdown}
    except Exception:
        return {"url": url, "error": "source failed fetch policy or was unavailable"}


async def _synthesize(query: str, docs: list[dict]) -> str:
    budget = input_budget(settings) - 512
    sources = [
        {"number": i + 1, "url": truncate_bytes(d["url"], 1024), "untrusted_text": ""}
        for i, d in enumerate(docs)
    ]
    payload = {"question": query, "untrusted_sources": sources}
    remaining = budget - len(json.dumps(payload, ensure_ascii=False).encode())
    if not docs or remaining < 512:
        raise ValueError("research question and source metadata exceed model budget")
    per_source = remaining // len(docs)
    for source, doc in zip(sources, docs, strict=True):
        # Account for JSON escaping, including newline/control-heavy pages.
        text = truncate_bytes(doc["markdown"], per_source)
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if len(json.dumps(text[:middle], ensure_ascii=False).encode()) - 2 <= per_source:
                low = middle
            else:
                high = middle - 1
        source["untrusted_text"] = text[:low]
    content = json.dumps(payload, ensure_ascii=False)
    allowed_citations = ", ".join(f"[{i + 1}]" for i in range(len(docs)))
    system = (
        UNTRUSTED_SYSTEM
        + " Write a concise report of at most four paragraphs. Cite each factual paragraph "
        + f"using actual source numbers. The only allowed citations are: {allowed_citations}. "
        + "Never write literal placeholders such as [n]. If sources do not support an answer, "
        + "explain that limitation with a citation to the source you inspected."
    )
    async with model_slots(settings).slot(), asyncio.timeout(settings.tool_timeout_s):
        if provider_for(settings.research_model, settings.research_provider) == "anthropic":
            from anthropic import AsyncAnthropic

            async with (
                httpx_client() as http_client,
                AsyncAnthropic(
                    api_key=settings.anthropic_api_key,
                    http_client=http_client,
                    max_retries=0,
                ) as client,
            ):
                msg = await client.messages.create(
                    model=settings.research_model,
                    max_tokens=settings.llm_output_tokens,
                    system=system,
                    messages=[{"role": "user", "content": content}],
                )
            if msg.stop_reason != "end_turn":
                raise ValueError("research output was truncated or incomplete")
            report = "".join(b.text for b in msg.content if b.type == "text")
        else:
            message = await ollama_chat(
                settings,
                {
                    "model": settings.research_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": content},
                    ],
                    "stream": False,
                    "options": {
                        "num_ctx": settings.ollama_num_ctx,
                        "num_predict": settings.llm_output_tokens,
                        "temperature": 0,
                    },
                },
            )
            report = message.get("content", "")
    citations = [int(n) for n in re.findall(r"\[(\d+)\]", report)]
    if (
        not report.strip()
        or not citations
        or re.search(r"\[n\]", report, flags=re.IGNORECASE)
        or any(n < 1 or n > len(docs) for n in citations)
    ):
        raise ValueError("research report has missing or invalid citations")
    return report


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def deep_research(
        query: Annotated[
            str, Field(min_length=1, max_length=2048, description="Research question.")
        ],
        max_sources: Annotated[int, Field(description="Top results to read.", ge=1, le=15)] = 5,
    ) -> dict:
        """Search/read bounded sources and return a report with checked citation indices."""
        if (
            provider_for(settings.research_model, settings.research_provider) == "anthropic"
            and not settings.anthropic_api_key
        ):
            return {"error": "ANTHROPIC_API_KEY is required for the Anthropic provider"}
        backend, fn = _pick_backend()
        try:
            hits = await fn(query, max_sources)
        except Exception:
            return {"error": "search provider was unavailable", "backend": backend}
        # Bound per-job workers without creating more fetches than server capacity.
        semaphore = asyncio.Semaphore(min(settings.max_concurrent_fetches, 3))

        async def read(url):
            async with semaphore:
                return await _grab(url)

        grabbed = await asyncio.gather(
            *(read(h["url"]) for h in hits[:max_sources] if h.get("url"))
        )
        docs = [d for d in grabbed if "error" not in d]
        failures = [d for d in grabbed if "error" in d]
        if not docs:
            return {"error": "no sources could be read", "backend": backend, "failures": failures}
        try:
            report = await _synthesize(query, docs)
        except ValueError:
            return {"error": "model report failed input/output or citation validation"}
        return {
            "query": query,
            "backend": backend,
            "sources": [{"url": d["url"], "title": d["title"]} for d in docs],
            "failures": failures,
            "report": report,
        }
