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


# --- fake HTTP client for Ollama --------------------------------------------
class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass


class _FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def post(self, url, json):
        return self.response


async def test_llm_extract_schema_returns_data(monkeypatch):
    monkeypatch.setattr(ex.settings, "extract_model", "claude-haiku-4-5")
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic",
        _fake_anthropic([_Block("tool_use", input={"title": "Hi", "price": 9})]),
    )
    out = await ex._llm_extract("page md", {"type": "object"}, None)
    assert out == {"data": {"title": "Hi", "price": 9}}


async def test_llm_extract_freeform_returns_text(monkeypatch):
    monkeypatch.setattr(ex.settings, "extract_model", "claude-haiku-4-5")
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic",
        _fake_anthropic([_Block("text", text="a summary")]),
    )
    out = await ex._llm_extract("page md", None, "summarise")
    assert out == {"text": "a summary"}


async def test_llm_extract_ollama_schema(monkeypatch):
    monkeypatch.setattr(ex.settings, "extract_model", "llama3.1")
    fake_response = _FakeResponse(
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "extract",
                            "arguments": {"title": "Ollama Book", "price": 10},
                        }
                    }
                ],
            }
        }
    )
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: _FakeAsyncClient(fake_response))
    out = await ex._llm_extract("page md", {"type": "object"}, None)
    assert out == {"data": {"title": "Ollama Book", "price": 10}}


async def test_llm_extract_ollama_freeform(monkeypatch):
    monkeypatch.setattr(ex.settings, "extract_model", "llama3.1")
    fake_response = _FakeResponse(
        {
            "message": {
                "role": "assistant",
                "content": "extracted text answer",
            }
        }
    )
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: _FakeAsyncClient(fake_response))
    out = await ex._llm_extract("page md", None, "summarise")
    assert out == {"text": "extracted text answer"}


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
