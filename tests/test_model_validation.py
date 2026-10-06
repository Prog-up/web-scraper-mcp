"""Invalid models, schemas, citations and prompt sizes cannot become successful data."""

import pytest

from web_scraper_mcp import llm
from web_scraper_mcp.tools import extract as ex
from web_scraper_mcp.tools import research

SCHEMA = {"type": "object", "properties": {"price": {"type": "number"}}, "required": ["price"]}


def test_model_validation_caps_nested_and_oversized_data():
    assert "error" in llm.validate_data("x" * 64_001, {})
    assert "error" in llm.validate_data([0] * 1025, {})
    nested = 0
    for _ in range(18):
        nested = [nested]
    assert "error" in llm.validate_data(nested, {})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "not-a-type"},
        {"$ref": "http://127.0.0.1/private"},
        {"$ref": "#"},
        {"type": "string", "pattern": "(a+)+$"},
        {"$id": "http://remote.example/"},
        {"type": "object", "properties": {"x": {"$dynamicRef": "https://remote.example/"}}},
    ],
)
def test_unsafe_or_invalid_schemas_are_rejected(schema):
    with pytest.raises(ValueError):
        llm.validate_schema(schema)


async def test_schema_invalid_json_never_returns_data(monkeypatch):
    monkeypatch.setattr(ex.settings, "extract_provider", "ollama")

    async def chat(*args):
        return {"content": '{"price":"wrong"}'}

    monkeypatch.setattr(ex, "ollama_chat", chat)
    result = await ex._llm_extract("untrusted page", SCHEMA, None)
    assert "error" in result and "data" not in result


async def test_wrong_tool_name_is_rejected(monkeypatch):
    monkeypatch.setattr(ex.settings, "extract_provider", "ollama")

    async def chat(*args):
        return {"tool_calls": [{"function": {"name": "other", "arguments": {"price": 10}}}]}

    monkeypatch.setattr(ex, "ollama_chat", chat)
    assert "error" in await ex._llm_extract("page", SCHEMA, None)


async def test_encoded_input_including_schema_stays_in_budget(monkeypatch):
    monkeypatch.setattr(ex.settings, "extract_provider", "ollama")

    async def chat(s, payload):
        import json

        assert len(payload["messages"][1]["content"].encode()) + len(
            json.dumps(SCHEMA).encode()
        ) <= llm.input_budget(s)
        assert payload["options"]["num_predict"] == s.llm_output_tokens
        assert "untrusted" in payload["messages"][0]["content"]
        return {"content": '{"price":10}'}

    monkeypatch.setattr(ex, "ollama_chat", chat)
    assert await ex._llm_extract('\n"\\é' * 100_000, SCHEMA, None) == {"data": {"price": 10}}


@pytest.mark.parametrize("report", ["fabricated [2]", "no citations", "invalid [0]"])
async def test_research_rejects_invalid_citations(monkeypatch, report):
    monkeypatch.setattr(research.settings, "research_provider", "ollama")

    async def chat(*args):
        return {"content": report}

    monkeypatch.setattr(research, "ollama_chat", chat)
    with pytest.raises(ValueError, match="citations"):
        await research._synthesize(
            "question", [{"url": "https://source.example/", "markdown": "source"}]
        )


async def test_research_fifteen_sources_keep_text_and_account_for_json_escaping(monkeypatch):
    import json

    monkeypatch.setattr(research.settings, "research_provider", "ollama")

    async def chat(s, payload):
        content = payload["messages"][1]["content"]
        assert len(content.encode()) <= llm.input_budget(s)
        sources = json.loads(content)["untrusted_sources"]
        assert len(sources) == 15
        assert all(len(source["untrusted_text"]) > 100 for source in sources)
        return {"content": "Evidence [1] and [15]"}

    monkeypatch.setattr(research, "ollama_chat", chat)
    assert (
        await research._synthesize(
            "Compare sources",
            [
                {"url": f"https://source.example/{i}", "markdown": '\n"\\é' * 10000}
                for i in range(15)
            ],
        )
        == "Evidence [1] and [15]"
    )
