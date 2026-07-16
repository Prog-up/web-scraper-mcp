"""extract — fetch a page and pull structured data with an LLM.

Uses Anthropic tool-use: the caller's JSON schema becomes the tool's
input_schema and we force the model to call it, so the result conforms to the
schema. Needs ANTHROPIC_API_KEY.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import to_markdown
from ..runtime import pool

# Cap the markdown we send to the model (~25k tokens). ponytail: simple char cap.
_MAX_INPUT_CHARS = 100_000


def _truncate(md: str) -> str:
    return md[:_MAX_INPUT_CHARS]


async def _llm_extract(markdown: str, schema: dict | None, prompt: str | None) -> dict:
    model = settings.extract_model
    instruction = prompt or "Extract the requested structured data from the page content."

    if model.startswith("claude-"):
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        if schema is not None:
            tool = {
                "name": "extract",
                "description": instruction,
                "input_schema": schema,
            }
            msg = await client.messages.create(  # type: ignore[call-overload]
                model=model,
                max_tokens=2048,
                tools=[tool],
                tool_choice={"type": "tool", "name": "extract"},
                messages=[{"role": "user", "content": f"{instruction}\n\n---\n{markdown}"}],
            )
            for block in msg.content:
                if block.type == "tool_use":
                    return {"data": block.input}
            return {"error": "model did not return structured output"}

        # No schema: free-form text answer.
        msg = await client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": f"{instruction}\n\n---\n{markdown}"}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        return {"text": text}

    # Ollama execution path
    import json

    import httpx

    url = settings.ollama_url("/api/chat")
    messages = [{"role": "user", "content": f"{instruction}\n\n---\n{markdown}"}]
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    if schema is not None:
        tool = {
            "type": "function",
            "function": {
                "name": "extract",
                "description": instruction,
                "parameters": schema,
            },
        }
        payload["tools"] = [tool]

    async with httpx.AsyncClient(timeout=settings.request_timeout_s * 2) as http_client:
        resp = await http_client.post(url, json=payload)

        resp.raise_for_status()
        data = resp.json()

    message = data.get("message", {})

    if schema is not None:
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            fn_info = tool_calls[0].get("function", {})
            return {"data": fn_info.get("arguments", {})}

        # Fallback: if model returned raw JSON in content instead of a tool call
        content = message.get("content", "").strip()
        try:
            if content.startswith("```"):
                content = content.split("```", 2)[1]
                if content.startswith("json"):
                    content = content[4:]
            parsed_json = json.loads(content.strip())
            return {"data": parsed_json}
        except Exception:
            return {"error": "Ollama model did not return structured tool call or valid JSON"}

    return {"text": message.get("content", "")}


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def extract(
        url: Annotated[str, Field(description="URL to extract from.")],
        json_schema: Annotated[
            dict | None,
            Field(description="JSON Schema describing the fields to extract (recommended)."),
        ] = None,
        prompt: Annotated[
            str | None, Field(description="Natural-language extraction instruction.")
        ] = None,
        render: Annotated[bool, Field(description="Force a browser render.")] = False,
    ) -> dict:
        """Extract structured data (JSON matching json_schema) or a text answer from a page."""
        if settings.extract_model.startswith("claude-") and not settings.anthropic_api_key:
            return {"error": "ANTHROPIC_API_KEY is not set — extract is unavailable."}
        if json_schema is None and prompt is None:
            return {"error": "provide json_schema and/or prompt."}
        result = await fetch(url, render=render, settings=settings, pool=pool)
        markdown = _truncate(to_markdown(result.html, result.url))
        out = await _llm_extract(markdown, json_schema, prompt)
        out["url"] = result.url
        return out
