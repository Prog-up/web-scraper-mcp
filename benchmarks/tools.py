"""Measure MCP tool calls against controlled upstreams or opt-in live providers.

Fixture mode uses HTTPX's in-memory transport (50 ms/page) with real MCP, parsers
and schema/citation validation. It does not measure DNS/TLS or model inference.
Live mode reads public documentation and uses the configured Ollama/search
backend; it refuses paid providers. No credentials or endpoint names are saved.
Browser interaction/sandbox tests remain in scripts/browser_features.py.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import resource
import statistics
import sys
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from fastmcp import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web_scraper_mcp.config import Settings, settings  # noqa: E402
from web_scraper_mcp.server import build_app  # noqa: E402
from web_scraper_mcp.tools import crawl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_URLS = [
    "https://www.python.org/doc/",
    "https://docs.python.org/3/library/asyncio-task.html",
    "https://playwright.dev/python/docs/locators",
]
QUERY = "Python asyncio TaskGroup documentation"
SCHEMA = {
    "type": "object",
    "properties": {"language": {"type": "string", "enum": ["Python"]}},
    "required": ["language"],
    "additionalProperties": False,
}


def html(path: str) -> str:
    links = "".join(f'<a href="/page/{i}">Article {i}</a>' for i in range(1, 13))
    return f"""<html><head><title>Python fixture {path}</title></head><body>
    <nav>Home About Login</nav><article><h1>Python documentation</h1>
    <p>Python supports asynchronous programming with asyncio. TaskGroup manages
    related asynchronous tasks, awaits their completion and propagates failures.</p>
    <p>This fixture describes Python, not a product for sale. The language is Python.</p>
    {links}</article><footer>Privacy Cookies Terms</footer></body></html>"""


async def run(mode: str, samples: int) -> dict:
    source_sha256 = hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted((ROOT / "src").rglob("*.py")))
    ).hexdigest()
    rows = []
    requests = 0
    inflight = 0
    peak = 0
    original_client = httpx.AsyncClient

    async def handler(request):
        nonlocal requests, inflight, peak
        requests += 1
        if request.url.host == "fixture.example":
            inflight += 1
            peak = max(peak, inflight)
            try:
                await asyncio.sleep(0.05)
                return httpx.Response(
                    200, text=html(request.url.path), headers={"content-type": "text/html"}
                )
            finally:
                inflight -= 1
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            message = {"role": "assistant", "content": "Python TaskGroup manages tasks [1]."}
            if payload.get("format"):
                message["content"] = json.dumps({"language": "Python"})
            return httpx.Response(200, json={"done": True, "message": message})
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Python", "url": "https://fixture.example/", "content": "Python"}
                ]
            },
        )

    class FixtureClient(original_client):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    async def measure(client, name, args, label=None, *, check=None):
        started = time.perf_counter()
        try:
            response = await client.call_tool(name, args, raise_on_error=False)
            data = response.data if isinstance(response.data, dict) else {}
            ok = not response.is_error and isinstance(response.data, dict) and not data.get("error")
            if ok and check:
                ok = bool(check(data))
            error = (
                (data.get("error") or "tool returned an error or failed result check")
                if not ok
                else None
            )
        except Exception as exc:
            data, ok, error = {}, False, type(exc).__name__
        row = {
            "tool": name,
            "case": label or name,
            "seconds": round(time.perf_counter() - started, 6),
            "ok": ok,
            "output_bytes": len(json.dumps(data, ensure_ascii=False).encode()),
        }
        if error:
            row["error"] = error
        for key in ("count", "pages_crawled", "status", "backend", "via"):
            if key in data:
                row[key] = data[key]
        if "sources" in data:
            row["sources_read"] = len(data["sources"])
            row["source_failures"] = len(data.get("failures", []))
        rows.append(row)
        print(json.dumps(row), flush=True)
        return data

    config = Settings(_env_file=None, transport="stdio")
    with patch.object(httpx, "AsyncClient", FixtureClient) if mode == "fixture" else nullcontext():
        async with Client(build_app(config), timeout=190) as client:
            inventory = sorted(tool.name for tool in await client.list_tools())
            urls = PUBLIC_URLS if mode == "live" else ["https://fixture.example/"]
            for url in urls:
                for _ in range(samples):
                    await measure(
                        client,
                        "scrape",
                        {"url": url, "include_links": True},
                        url,
                        check=lambda data: bool(data.get("markdown")) and bool(data.get("title")),
                    )
            await measure(
                client, "map", {"url": urls[0], "limit": 10}, check=lambda d: 0 < d["count"] <= 10
            )
            await measure(
                client,
                "search",
                {"query": QUERY, "max_results": 3},
                check=lambda d: 0 < d.get("count", 0) <= 3,
            )
            for _ in range(samples):
                started = time.perf_counter()
                job = await measure(
                    client,
                    "crawl",
                    {"url": urls[0], "max_pages": 3 if mode == "live" else 13, "max_depth": 1},
                )
                if "job_id" in job:
                    # Await the real background task; do not add arbitrary polling delays
                    # to the measured completion time. Polling latency is measured separately.
                    await crawl._jobs[job["job_id"]].task
                    result = await measure(
                        client,
                        "check_crawl_status",
                        {"job_id": job["job_id"]},
                        "completed crawl",
                        check=lambda d: d.get("status") == "completed" and d["pages_crawled"] > 0,
                    )
                    rows.append(
                        {
                            "tool": "crawl",
                            "case": "completion",
                            "seconds": round(time.perf_counter() - started, 6),
                            "ok": result.get("status") == "completed",
                            "pages_crawled": result.get("pages_crawled", 0),
                        }
                    )
            cancelled = await measure(client, "crawl", {"url": urls[0]}, "cancel setup")
            if "job_id" in cancelled:
                await measure(
                    client,
                    "check_crawl_status",
                    {"job_id": cancelled["job_id"], "cancel": True},
                    "cancel",
                    check=lambda d: d.get("status") == "cancelled",
                )
            for name, args in [
                (
                    "extract",
                    {
                        "url": urls[0],
                        "json_schema": SCHEMA,
                        "prompt": "Which programming language is this documentation for?",
                    },
                ),
                (
                    "extract",
                    {"url": urls[0], "prompt": "Name the programming language in one word."},
                ),
                ("deep_research", {"query": QUERY, "max_sources": 2}),
            ]:
                await measure(
                    client,
                    name,
                    args,
                    "structured"
                    if "json_schema" in args
                    else "text"
                    if name == "extract"
                    else "two-source research",
                    check=(lambda d: d.get("data") == {"language": "Python"})
                    if "json_schema" in args
                    else (lambda d: "Python" in d.get("text", ""))
                    if name == "extract"
                    else (lambda d: bool(d.get("sources")) and "[" in d.get("report", "")),
                )
    grouped = {}
    for row in rows:
        grouped.setdefault(row["tool"] + " / " + row["case"], []).append(row["seconds"])
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "samples": samples,
        "python": platform.python_version(),
        "models": {"extract": settings.extract_model, "research": settings.research_model},
        "settings": {
            "ollama_num_ctx": settings.ollama_num_ctx,
            "llm_input_bytes": settings.llm_input_bytes,
            "llm_output_tokens": settings.llm_output_tokens,
            "crawl_concurrency": settings.crawl_concurrency,
            "max_concurrent_fetches": settings.max_concurrent_fetches,
            "respect_robots": settings.respect_robots,
            "per_domain_delay_s": settings.per_domain_delay_s,
        },
        "source_sha256": source_sha256,
        "fixture_delay_s": 0.05 if mode == "fixture" else None,
        "fixture_requests": requests if mode == "fixture" else None,
        "peak_fixture_fetches": peak if mode == "fixture" else None,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "registered_tools": inventory,
        "rows": rows,
        "median_seconds": {key: round(statistics.median(v), 6) for key, v in grouped.items()},
        "limitations": "Small diagnostic sample; fixture mode mocks network/providers. "
        "Peak RSS includes the harness. Built-in service hardware/cache state is unknown.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="Scrape and crawl repetitions; other cases run once.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 10:
        parser.error("samples must be between 1 and 10")
    changes = {
        "browser_enabled": False,
        "egress_proxy_url": None,
        "extract_provider": "ollama",
        "research_provider": "ollama",
    }
    if args.mode == "fixture":
        changes.update(
            {
                "respect_robots": False,
                "per_domain_delay_s": 0,
                "searxng_url": "https://fixture-search.example",
                "tavily_api_key": None,
                "brave_api_key": None,
            }
        )
    elif settings.tavily_api_key or settings.brave_api_key or settings.anthropic_api_key:
        parser.error("live benchmark refuses configured paid API providers")
    # Changes affect only this benchmark process, never deployment configuration.
    with patch.multiple(settings, **changes):
        if args.mode == "fixture":
            result = asyncio.run(run("fixture", args.samples))
        else:
            result = asyncio.run(run(args.mode, args.samples))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not all(row["ok"] for row in result["rows"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
