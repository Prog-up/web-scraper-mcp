"""MCP contract, HTTP authentication, admission and body caps."""

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from web_scraper_mcp.config import Settings
from web_scraper_mcp.limits import CapacityError, Limiter
from web_scraper_mcp.server import BodyLimit, build_app


@pytest.mark.parametrize("token", [None, "", "  "])
def test_http_without_token_refuses_startup(token):
    with pytest.raises(ValueError, match="AUTH_TOKEN"):
        build_app(Settings(_env_file=None, auth_token=token, transport="http"))


async def test_stdio_tool_contract():
    app = build_app(Settings(_env_file=None, auth_token=None, transport="stdio"))
    assert {t.name for t in await app.list_tools()} == {
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


@pytest.mark.parametrize(
    "authorization,expected", [(None, 401), ("Bearer wrong", 401), ("Bearer test-token", 200)]
)
async def test_http_initialize_requires_correct_token(authorization, expected):
    config = Settings(_env_file=None, transport="http", auth_token="test-token")  # noqa: S106
    # ASGITransport reports immediate disconnects after sending the request body;
    # use JSON here. Real streaming HTTP is covered by test_mcp_transports.
    app = build_app(config).http_app(json_response=True)
    headers = {"Accept": "application/json, text/event-stream"}
    if authorization:
        headers["Authorization"] = authorization
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1"
        ) as client,
    ):
        response = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
    assert response.status_code == expected


async def test_chunked_body_cap_precedes_application():
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    chunks = iter(
        [
            {"type": "http.request", "body": b"a" * 600, "more_body": True},
            {"type": "http.request", "body": b"b" * 600, "more_body": False},
        ]
    )

    async def receive():
        return next(chunks)

    sent = []

    async def send(message):
        sent.append(message)

    await BodyLimit(app, 1024)({"type": "http"}, receive, send)
    assert not called
    assert sent[0]["status"] == 413


async def test_admission_rejects_excess_and_releases_after_cancellation():
    slots = Limiter(1)
    event = asyncio.Event()

    async def work():
        async with slots.slot():
            await event.wait()

    task = asyncio.create_task(work())
    await asyncio.sleep(0)
    with pytest.raises(CapacityError):
        async with slots.slot():
            pass
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert slots.active == 0


@pytest.mark.parametrize(
    "values",
    [
        {"max_concurrent_pages": 0},
        {"max_response_bytes": -1},
        {"request_timeout_s": 0},
        {"per_domain_delay_s": -1},
    ],
)
def test_invalid_resource_config_is_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "host,expected",
    [
        ("localhost", "http://localhost:11434/api/chat"),
        ("[::1]", "http://[::1]:11434/api/chat"),
        ("https://model.example/base", "https://model.example:11434/base/api/chat"),
        ("http://model.example:1234/", "http://model.example:1234/api/chat"),
    ],
)
def test_ollama_url_uses_authority_components(host, expected):
    assert Settings(_env_file=None, ollama_host=host).ollama_url("/api/chat") == expected


@pytest.mark.parametrize("value,expected", [("", None), ("true", True), ("false", False)])
def test_ollama_thinking_config(value, expected):
    assert Settings(_env_file=None, ollama_think=value).ollama_think is expected
