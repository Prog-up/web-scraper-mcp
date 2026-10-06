"""Exercise registered MCP tools and real provider SDKs with controlled upstreams."""

import asyncio
import json
import time

import httpx
import pytest
from fastmcp import Client

from web_scraper_mcp import fetch as fetching
from web_scraper_mcp.config import Settings, settings
from web_scraper_mcp.server import build_app
from web_scraper_mcp.tools import crawl

TOOLS = {
    "scrape",
    "search",
    "extract",
    "deep_research",
    "crawl",
    "check_crawl_status",
    "map",
    "browser_navigate",
    "browser_act",
    "browser_close",
}
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
HTML = """<html><head><title>Fixture article</title></head><body>
<article><h1>Fixture article</h1><p>Reliable fixture content for extraction and research.
An article describes how the documented features behave when the server fetches public pages.</p>
<a href="/next">Next article</a><a href="https://other.example/external">Other</a>
<a href="https://SITE.EXAMPLE:443/next#fragment">Duplicate next</a>
</article></body></html>"""


@pytest.fixture
def upstream(monkeypatch):
    for name, value in {
        "respect_robots": False,
        "per_domain_delay_s": 0,
        "browser_enabled": False,
        "egress_proxy_url": None,
        "extract_provider": "ollama",
        "research_provider": "ollama",
        "extract_model": "fixture",
        "research_model": "fixture",
        "ollama_host": "http://model.example:11434",
        "searxng_url": "https://search.example",
        "brave_api_key": None,
        "tavily_api_key": None,
    }.items():
        monkeypatch.setattr(settings, name, value)
    fetching._robots_cache.clear()
    fetching._domain_states.clear()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "site.example":
            if request.url.path == "/missing":
                return httpx.Response(404, text="missing")
            return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})
        if request.url.host == "api.anthropic.com":
            payload = json.loads(request.content)
            content = (
                [
                    {
                        "type": "tool_use",
                        "id": "fixture_call",
                        "name": "extract",
                        "input": {"title": "Fixture article"},
                    }
                ]
                if payload.get("tools")
                else [{"type": "text", "text": "Fixture summary [1]"}]
            )
            return httpx.Response(
                200,
                json={
                    "id": "fixture_msg",
                    "type": "message",
                    "role": "assistant",
                    "model": payload["model"],
                    "content": content,
                    "stop_reason": "tool_use" if payload.get("tools") else "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 50, "output_tokens": 20},
                },
            )
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            message = {"role": "assistant", "content": "Fixture summary [1]"}
            if payload.get("tools"):
                message["tool_calls"] = [
                    {"function": {"name": "extract", "arguments": {"title": "Fixture article"}}}
                ]
            return httpx.Response(
                200, json={"done": True, "done_reason": "stop", "message": message}
            )
        if request.url.host == "api.search.brave.com":
            return httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "Fixture",
                                "url": "https://site.example/",
                                "description": "snippet",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Fixture", "url": "https://site.example/", "content": "snippet"},
                    {
                        "title": "Missing",
                        "url": "https://site.example/missing",
                        "content": "missing",
                    },
                ]
            },
        )

    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    class FixtureClient(original):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FixtureClient)
    return requests


@pytest.fixture
async def client(upstream):
    async with Client(build_app(Settings(_env_file=None, transport="stdio"))) as client:
        yield client


async def test_registered_tool_inventory(client):
    assert {tool.name for tool in await client.list_tools()} == TOOLS


async def test_scrape_optional_outputs_and_map_canonical_links(client):
    result = (
        await client.call_tool(
            "scrape",
            {
                "url": "https://site.example/",
                "include_links": True,
                "include_raw_html": True,
            },
        )
    ).data
    assert result["title"] == "Fixture article"
    assert "Reliable fixture content" in result["markdown"]
    assert result["html"] == HTML
    assert len(result["links"]) == 2
    same = (await client.call_tool("map", {"url": "https://site.example/"})).data
    assert same["links"] == ["https://site.example/next"]
    all_links = (
        await client.call_tool(
            "map", {"url": "https://site.example/", "same_domain": False, "limit": 1}
        )
    ).data
    assert all_links["count"] == 1


@pytest.mark.parametrize("provider", ["ollama", "anthropic"])
async def test_extract_structured_and_freeform_through_real_sdk(client, monkeypatch, provider):
    monkeypatch.setattr(settings, "extract_provider", provider)
    monkeypatch.setattr(settings, "anthropic_api_key", "fixture-key")
    structured = (
        await client.call_tool("extract", {"url": "https://site.example/", "json_schema": SCHEMA})
    ).data
    assert structured["data"] == {"title": "Fixture article"}
    freeform = (
        await client.call_tool("extract", {"url": "https://site.example/", "prompt": "Summarize"})
    ).data
    assert freeform["text"] == "Fixture summary [1]"


@pytest.mark.parametrize("provider", ["ollama", "anthropic"])
async def test_research_keeps_good_sources_and_explicit_failures(client, monkeypatch, provider):
    monkeypatch.setattr(settings, "research_provider", provider)
    monkeypatch.setattr(settings, "anthropic_api_key", "fixture-key")
    result = (
        await client.call_tool("deep_research", {"query": "fixture question", "max_sources": 2})
    ).data
    assert result["sources"] == [{"url": "https://site.example/", "title": "Fixture article"}]
    assert result["failures"][0]["url"] == "https://site.example/missing"
    assert result["report"] == "Fixture summary [1]"


@pytest.mark.parametrize("backend", ["searxng", "brave", "tavily", "duckduckgo"])
async def test_search_each_backend_and_real_request_contract(
    client, upstream, monkeypatch, backend
):
    if backend == "brave":
        monkeypatch.setattr(settings, "brave_api_key", "fixture-key")
    elif backend == "tavily":
        monkeypatch.setattr(settings, "tavily_api_key", "fixture-key")
    elif backend == "duckduckgo":
        monkeypatch.setattr(settings, "searxng_url", None)

        class DDGS:
            def __init__(self, **kwargs):
                assert kwargs["timeout"] > 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def text(self, query, max_results):
                assert query == "fixture question" and max_results == 1
                return [{"title": "Fixture", "href": "https://site.example/", "body": "snippet"}]

        monkeypatch.setattr("ddgs.DDGS", DDGS)
    result = (
        await client.call_tool("search", {"query": "fixture question", "max_results": 1})
    ).data
    assert result["backend"] == backend
    assert result["count"] == 1
    assert result["results"][0] == {
        "title": "Fixture",
        "url": "https://site.example/",
        "content": "snippet",
    }
    if backend == "brave":
        assert upstream[-1].headers["X-Subscription-Token"] == "fixture-key"
        assert upstream[-1].url.params["q"] == "fixture question"
    elif backend == "tavily":
        assert json.loads(upstream[-1].content)["api_key"] == "fixture-key"
    elif backend == "searxng":
        assert upstream[-1].url.params["format"] == "json"


async def test_crawl_job_polling_and_finished_expiry(client, monkeypatch):
    started = (
        await client.call_tool("crawl", {"url": "https://site.example/", "max_pages": 2})
    ).data
    job = crawl._jobs[started["job_id"]]
    await job.task
    result = (await client.call_tool("check_crawl_status", {"job_id": job.job_id})).data
    assert result["status"] == "completed" and result["pages_crawled"] == 2
    assert {page["url"] for page in result["pages"]} == {
        "https://site.example/",
        "https://site.example/next",
    }
    brief = (
        await client.call_tool("check_crawl_status", {"job_id": job.job_id, "include_pages": False})
    ).data
    assert "pages" not in brief
    job.expires_at = time.monotonic() - 1
    assert "error" in (await client.call_tool("check_crawl_status", {"job_id": job.job_id})).data


async def test_crawl_capacity_cancel_and_memory_caps(client, monkeypatch):
    waiting = asyncio.Event()
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await waiting.wait()

    monkeypatch.setattr(crawl, "_crawl_one", blocked)
    monkeypatch.setattr(settings, "max_concurrent_crawls", 1)
    started = (await client.call_tool("crawl", {"url": "https://site.example/"})).data
    await entered.wait()
    assert "error" in (await client.call_tool("crawl", {"url": "https://site.example/other"})).data
    stopped = (
        await client.call_tool("check_crawl_status", {"job_id": started["job_id"], "cancel": True})
    ).data
    assert stopped["status"] == "cancelled"

    async def oversized(*args):
        return {"url": "https://site.example/", "markdown": "x" * 2000}, []

    monkeypatch.setattr(crawl, "_crawl_one", oversized)
    monkeypatch.setattr(settings, "crawl_result_bytes", 1024)
    job = crawl.CrawlJob("bounded")
    await crawl._run(job, "https://site.example/", 100, 5, True)
    assert job.truncated and not job.pages and job.result_bytes <= 1024


async def test_invalid_arguments_and_unknown_ids_fail_predictably(client):
    for name, arguments in [
        ("scrape", {"url": "file:///etc/passwd"}),
        ("map", {"url": "https://site.example/", "limit": 0}),
        ("crawl", {"url": "https://site.example/", "max_pages": 0}),
        ("search", {"query": "", "max_results": 1}),
        (
            "extract",
            {"url": "https://site.example/", "json_schema": {"$ref": "https://private.example/"}},
        ),
    ]:
        result = await client.call_tool(name, arguments, raise_on_error=False)
        assert result.is_error or "error" in result.data
    assert "error" in (await client.call_tool("browser_close", {"session_id": "missing"})).data


async def test_crawl_frontier_bound_limits_fetch_attempts(client, monkeypatch):
    monkeypatch.setattr(settings, "crawl_frontier_limit", 2)
    calls = []

    async def many_links(url, same_domain):
        calls.append(url)
        return {"url": url, "title": "Fixture", "markdown": "article"}, [
            f"https://site.example/{i}" for i in range(1000)
        ]

    monkeypatch.setattr(crawl, "_crawl_one", many_links)
    job = crawl.CrawlJob("frontier")
    await crawl._run(job, "https://site.example/", 100, 5, True)
    assert job.status == "completed" and job.truncated
    assert calls == ["https://site.example/", "https://site.example/0"]


async def test_crawl_total_deadline_stops_slow_fetch(client, monkeypatch):
    monkeypatch.setattr(settings, "crawl_timeout_s", 0.01)

    async def slow_page(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(crawl, "_crawl_one", slow_page)
    job = crawl.CrawlJob("deadline")
    await crawl._run(job, "https://site.example/", 10, 2, True)
    assert job.status == "failed" and job.error == "crawl exceeded total deadline"
    assert not job.pages and job.expires_at > time.monotonic()


async def test_server_shutdown_cancels_and_forgets_background_jobs(upstream, monkeypatch):
    started = asyncio.Event()

    async def slow_page(*args):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(crawl, "_crawl_one", slow_page)
    async with Client(build_app(Settings(_env_file=None, transport="stdio"))) as client:
        result = (await client.call_tool("crawl", {"url": "https://site.example/"})).data
        job = crawl._jobs[result["job_id"]]
        async with asyncio.timeout(2):
            await started.wait()
        assert job.task is not None and not job.task.done()
    assert job.task.done() and job.status == "cancelled"
    assert not crawl._jobs and not crawl._tasks
