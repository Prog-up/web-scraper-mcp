"""Fetch a page and return locally validated structured model output."""

from __future__ import annotations

import asyncio
import json
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
    validate_data,
    validate_schema,
)
from ..parse import to_markdown
from ..runtime import pool
from ..work import work

_MAX_INPUT_CHARS = 100_000  # Backward-compatible helper ceiling; actual requests use byte budgets.


def _truncate(md: str) -> str:
    return md[:_MAX_INPUT_CHARS]


async def _llm_extract(markdown: str, schema: dict | None, prompt: str | None) -> dict:
    try:
        await work.run(validate_schema, schema)
    except ValueError:
        return {"error": "invalid or unsupported JSON schema"}
    model = settings.extract_model
    provider = provider_for(model, settings.extract_provider)
    instruction = prompt or "Extract the requested structured data from the page content."
    overhead = len(json.dumps(schema or {}).encode()) + len(instruction.encode())
    remaining = (input_budget(settings) - overhead - 512) // 2
    if remaining < 512:
        return {"error": "prompt and schema exceed model input budget"}
    content = json.dumps(
        {"task": instruction, "untrusted_page": truncate_bytes(markdown, remaining)},
        ensure_ascii=False,
    )
    if len(content.encode()) + len(json.dumps(schema or {}).encode()) > input_budget(settings):
        return {"error": "encoded model input exceeds budget"}
    async with model_slots(settings).slot(), asyncio.timeout(settings.tool_timeout_s):
        if provider == "anthropic":
            from anthropic import AsyncAnthropic

            async with (
                httpx_client() as http_client,
                AsyncAnthropic(
                    api_key=settings.anthropic_api_key,
                    http_client=http_client,
                    max_retries=0,
                ) as client,
            ):
                kwargs: dict = {
                    "model": model,
                    "max_tokens": settings.llm_output_tokens,
                    "system": UNTRUSTED_SYSTEM,
                    "messages": [{"role": "user", "content": content}],
                }
                if schema is not None:
                    kwargs["tools"] = [
                        {"name": "extract", "description": instruction, "input_schema": schema}
                    ]
                    kwargs["tool_choice"] = {"type": "tool", "name": "extract"}
                msg = await client.messages.create(**kwargs)
            if msg.stop_reason not in ("end_turn", "tool_use"):
                return {"error": "model output was incomplete or truncated"}
            if schema is not None:
                for block in msg.content:
                    if block.type == "tool_use" and block.name == "extract":
                        return await work.run(validate_data, block.input, schema)
                return {"error": "model did not return the requested tool call"}
            return {"text": "".join(b.text for b in msg.content if b.type == "text")}
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": UNTRUSTED_SYSTEM},
                {"role": "user", "content": content},
            ],
            "stream": False,
            "options": {
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": settings.llm_output_tokens,
            },
        }
        if schema is not None:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": "extract",
                        "description": instruction,
                        "parameters": schema,
                    },
                }
            ]
        message = await ollama_chat(settings, payload)
        if schema is None:
            return {"text": message.get("content", "")}
        calls = message.get("tool_calls", [])
        if calls:
            function = calls[0].get("function", {})
            if function.get("name") != "extract" or not isinstance(function.get("arguments"), dict):
                return {"error": "model returned an invalid extraction tool call"}
            return await work.run(validate_data, function["arguments"], schema)
        content = message.get("content", "").strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            data = json.loads(content.strip())
        except (ValueError, RecursionError):
            return {"error": "model did not return valid JSON"}
        return await work.run(validate_data, data, schema)


def httpx_client():
    import httpx

    return httpx.AsyncClient(
        trust_env=False,
        proxy=settings.egress_proxy_url,
        timeout=httpx.Timeout(settings.tool_timeout_s, connect=min(settings.request_timeout_s, 10)),
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def extract(
        url: Annotated[str, Field(max_length=8192, description="URL to extract from.")],
        json_schema: Annotated[dict | None, Field(description="JSON Schema 2020-12.")] = None,
        prompt: Annotated[
            str | None, Field(max_length=4096, description="Extraction task.")
        ] = None,
        render: Annotated[bool, Field(description="Force a browser render.")] = False,
    ) -> dict:
        """Extract data matching JSON Schema, or a text answer, from a page."""
        if (
            provider_for(settings.extract_model, settings.extract_provider) == "anthropic"
            and not settings.anthropic_api_key
        ):
            return {"error": "ANTHROPIC_API_KEY is required for the Anthropic provider"}
        if json_schema is None and prompt is None:
            return {"error": "provide json_schema and/or prompt"}
        await work.run(validate_schema, json_schema)
        result = await fetch(url, render=render, settings=settings, pool=pool)
        markdown = await work.run(to_markdown, result.html, result.url)
        out = await _llm_extract(markdown, json_schema, prompt)
        out["url"] = result.url
        return out
