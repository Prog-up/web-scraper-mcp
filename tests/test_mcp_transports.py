"""Real HTTP and stdio MCP roundtrips against a local source/search/model fixture."""

import asyncio
import socket
import sys
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from web_scraper_mcp.config import Settings, settings
from web_scraper_mcp.llm import ollama_chat
from web_scraper_mcp.server import BodyLimit, build_app

HTML = """<html><head><title>Transport fixture</title></head><body><article>
<h1>Transport fixture</h1><p>This is real HTTP fixture content used to verify the MCP
server through its public transports and provider adapters.</p><a href="/next">Next</a>
</article></body></html>"""


@asynccontextmanager
async def serve(app):
    ready = asyncio.Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            ready.set()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = Server(uvicorn.Config(app, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            await ready.wait()
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


@pytest.fixture
async def fixture_server():
    requests = []

    async def endpoint(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /private")
        if request.url.path == "/search":
            return JSONResponse(
                {
                    "results": [
                        {
                            "title": "Transport fixture",
                            "url": str(request.base_url),
                            "content": "snippet",
                        }
                    ]
                }
            )
        if request.url.path == "/api/chat":
            payload = await request.json()
            message = {"role": "assistant", "content": "Transport summary [1]"}
            if payload.get("tools"):
                message["tool_calls"] = [
                    {
                        "function": {
                            "name": "extract",
                            "arguments": {"title": "Transport fixture"},
                        }
                    }
                ]
            return JSONResponse({"done": True, "done_reason": "stop", "message": message})
        if request.url.path in ("/", "/next"):
            return HTMLResponse(HTML)
        return PlainTextResponse("Missing", status_code=404)

    app = Starlette(routes=[Route("/{path:path}", endpoint, methods=["GET", "POST"])])
    async with serve(app) as url:
        yield url, requests


async def exercise_tools(client, source):
    tools = {tool.name for tool in await client.list_tools()}
    assert len(tools) == 10 and {"crawl", "map", "browser_act"} <= tools
    scraped = (
        await client.call_tool(
            "scrape",
            {
                "url": source,
                "include_links": True,
                "include_raw_html": True,
            },
        )
    ).data
    assert scraped["title"] == "Transport fixture" and scraped["html"] == HTML
    mapped = (await client.call_tool("map", {"url": source})).data
    assert mapped["links"] == [source + "/next"]
    searched = (
        await client.call_tool("search", {"query": "transport fixture", "max_results": 1})
    ).data
    assert searched["backend"] == "searxng" and searched["count"] == 1
    structured = (
        await client.call_tool(
            "extract",
            {
                "url": source,
                "json_schema": {"type": "object", "required": ["title"]},
            },
        )
    ).data
    assert structured["data"] == {"title": "Transport fixture"}
    text = (await client.call_tool("extract", {"url": source, "prompt": "Summarize"})).data
    assert text["text"] == "Transport summary [1]"
    research = (
        await client.call_tool("deep_research", {"query": "fixture", "max_sources": 1})
    ).data
    assert research["report"] == "Transport summary [1]" and len(research["sources"]) == 1
    job = (await client.call_tool("crawl", {"url": source, "max_pages": 2})).data
    async with asyncio.timeout(5):
        for _ in range(200):
            result = (await client.call_tool("check_crawl_status", {"job_id": job["job_id"]})).data
            if result["status"] != "running":
                break
            await asyncio.sleep(0.01)
    assert result["status"] == "completed" and result["pages_crawled"] == 2


async def test_stdio_subprocess_roundtrips(fixture_server, tmp_path):
    source, requests = fixture_server
    transport = StdioTransport(
        sys.executable,
        ["-m", "web_scraper_mcp.server"],
        cwd=str(tmp_path),
        keep_alive=False,
        env={
            "SCRAPER_TRANSPORT": "stdio",
            "SCRAPER_AUTH_TOKEN": "",
            "SCRAPER_ALLOW_PRIVATE_NETWORKS": "true",
            "SCRAPER_RESPECT_ROBOTS": "true",
            "SCRAPER_BROWSER_ENABLED": "false",
            "SCRAPER_PER_DOMAIN_DELAY_S": "0",
            "OLLAMA_HOST": source,
            "SCRAPER_EXTRACT_PROVIDER": "ollama",
            "SCRAPER_RESEARCH_PROVIDER": "ollama",
            "SCRAPER_EXTRACT_MODEL": "fixture",
            "SCRAPER_RESEARCH_MODEL": "fixture",
            "SCRAPER_SEARXNG_URL": source,
            "BRAVE_API_KEY": "",
            "TAVILY_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
        },
    )
    async with Client(transport, timeout=10) as client:
        await exercise_tools(client, source)
    assert "/robots.txt" in requests and "/api/chat" in requests


async def test_authenticated_http_roundtrips(fixture_server, monkeypatch):
    source, requests = fixture_server
    for name, value in {
        "transport": "http",
        "auth_token": "fixture-transport-token",
        "allow_private_networks": True,
        "respect_robots": True,
        "browser_enabled": False,
        "per_domain_delay_s": 0,
        "egress_proxy_url": None,
        "ollama_host": source,
        "extract_provider": "ollama",
        "research_provider": "ollama",
        "extract_model": "fixture",
        "research_model": "fixture",
        "searxng_url": source,
        "brave_api_key": None,
        "tavily_api_key": None,
    }.items():
        monkeypatch.setattr(settings, name, value)
    app = build_app(settings).http_app(
        middleware=[Middleware(BodyLimit, maximum=settings.max_request_bytes)]
    )
    async with serve(app) as endpoint:
        transport = StreamableHttpTransport(
            endpoint + "/mcp",
            headers={"Authorization": "Bearer fixture-transport-token"},
        )
        async with Client(transport, timeout=10) as client:
            await exercise_tools(client, source)
    assert "/robots.txt" in requests and "/api/chat" in requests


@pytest.mark.parametrize("thinking", [False, True, None])
async def test_model_generation_uses_tool_deadline_not_fetch_timeout(thinking):
    received = []

    async def slow_model(request):
        received.append(await request.json())
        await asyncio.sleep(0.1)
        return JSONResponse({"done": True, "done_reason": "stop", "message": {"content": "answer"}})

    async with serve(Starlette(routes=[Route("/api/chat", slow_model, methods=["POST"])])) as url:
        config = Settings(
            _env_file=None,
            ollama_host=url,
            request_timeout_s=0.01,
            tool_timeout_s=2,
            ollama_think=thinking,
        )
        assert await ollama_chat(config, {"model": "fixture"}) == {"content": "answer"}
    assert received[0].get("think") is thinking
    assert ("think" in received[0]) is (thinking is not None)


async def test_model_total_deadline_still_stops_generation():
    async def slow_model(request):
        await asyncio.sleep(0.1)
        return JSONResponse({"done": True, "message": {"content": "late answer"}})

    async with serve(Starlette(routes=[Route("/api/chat", slow_model, methods=["POST"])])) as url:
        config = Settings(_env_file=None, ollama_host=url, tool_timeout_s=0.01)
        with pytest.raises((TimeoutError, httpx.TimeoutException)):
            await ollama_chat(config, {"model": "fixture"})
