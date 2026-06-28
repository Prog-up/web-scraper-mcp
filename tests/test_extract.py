"""extract LLM plumbing (mocked Anthropic) + search backend selection. No network."""

import pytest

from web_scraper_mcp.tools import extract as ex
from web_scraper_mcp.tools import search as se


def test_truncate_caps_input():
    long = "x" * (ex._MAX_INPUT_CHARS + 5000)
    assert len(ex._truncate(long)) == ex._MAX_INPUT_CHARS


# --- fake Anthropic client -------------------------------------------------
class _Block:
    def __init__(self, type, input=None, text=None):
        self.type = type
        self.input = input
        self.text = text


class _Msg:
    def __init__(self, content):
        self.content = content


class _Messages:
    def __init__(self, content):
        self._content = content

    async def create(self, **_):
        return _Msg(self._content)


def _fake_anthropic(content):
    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages(content)

    return _Client


async def test_llm_extract_schema_returns_data(monkeypatch):
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic",
        _fake_anthropic([_Block("tool_use", input={"title": "Hi", "price": 9})]),
    )
    out = await ex._llm_extract("page md", {"type": "object"}, None)
    assert out == {"data": {"title": "Hi", "price": 9}}


async def test_llm_extract_freeform_returns_text(monkeypatch):
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic",
        _fake_anthropic([_Block("text", text="a summary")]),
    )
    out = await ex._llm_extract("page md", None, "summarise")
    assert out == {"text": "a summary"}


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"tavily_api_key": "t"}, "tavily"),
        ({"brave_api_key": "b"}, "brave"),
        ({"searxng_url": "http://sx"}, "searxng"),
        ({}, "duckduckgo"),
    ],
)
def test_search_backend_selection(monkeypatch, env, expected):
    for attr in ("tavily_api_key", "brave_api_key", "searxng_url"):
        monkeypatch.setattr(se.settings, attr, env.get(attr), raising=False)
    backend, _ = se._pick_backend()
    assert backend == expected
