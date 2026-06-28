"""interact — drive a persistent headless browser session for multi-step tasks.

Returns accessibility (ARIA) snapshots rather than screenshots: token-cheap and
the agent acts via selectors (CSS, text=, role=) it reads from the snapshot.
ponytail: sessions live in memory, capped; oldest is evicted past the cap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..runtime import pool
from ..security import validate_url

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

_MAX_SESSIONS = 5
_sessions: dict[str, tuple[BrowserContext, Page]] = {}


async def _snapshot(session_id: str, page: Page) -> dict:
    return {
        "session_id": session_id,
        "url": page.url,
        "title": await page.title(),
        "snapshot": await page.locator("body").aria_snapshot(),
    }


async def _evict_if_full() -> None:
    while len(_sessions) >= _MAX_SESSIONS:
        sid, (context, _) = next(iter(_sessions.items()))
        del _sessions[sid]
        try:
            await context.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("evict close failed: %s", exc)


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def browser_navigate(
        url: Annotated[str, Field(description="URL to open.")],
        session_id: Annotated[
            str | None, Field(description="Reuse an existing session, or omit to start one.")
        ] = None,
    ) -> dict:
        """Open a URL in a (new or existing) browser session; returns an ARIA snapshot."""
        validate_url(url, allow_private=settings.allow_private_networks)
        if session_id and session_id in _sessions:
            _, page = _sessions[session_id]
        else:
            await _evict_if_full()
            context, page = await pool.new_session()
            session_id = uuid4().hex
            _sessions[session_id] = (context, page)
        await page.goto(
            url, timeout=settings.request_timeout_s * 1000, wait_until="domcontentloaded"
        )
        return await _snapshot(session_id, page)

    @mcp.tool
    async def browser_act(
        session_id: Annotated[str, Field(description="Session from browser_navigate.")],
        action: Annotated[str, Field(description="click | fill | press | select | wait")],
        selector: Annotated[
            str | None, Field(description="Target selector (CSS, text=, role=).")
        ] = None,
        value: Annotated[
            str | None, Field(description="Text to fill / key to press / option to select.")
        ] = None,
    ) -> dict:
        """Perform one action in a session and return the updated ARIA snapshot."""
        if session_id not in _sessions:
            return {"error": f"unknown session_id: {session_id}"}
        _, page = _sessions[session_id]
        try:
            if action == "click":
                await page.click(selector)  # type: ignore[arg-type]
            elif action == "fill":
                await page.fill(selector, value or "")  # type: ignore[arg-type]
            elif action == "press":
                await page.press(selector or "body", value or "Enter")
            elif action == "select":
                await page.select_option(selector, value or "")  # type: ignore[arg-type]
            elif action == "wait":
                await page.wait_for_selector(selector)  # type: ignore[arg-type]
            else:
                return {"error": f"unknown action: {action}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{action} failed: {exc}", "session_id": session_id}
        return await _snapshot(session_id, page)

    @mcp.tool
    async def browser_close(
        session_id: Annotated[str, Field(description="Session to close.")],
    ) -> dict:
        """Close a browser session and free its resources."""
        entry = _sessions.pop(session_id, None)
        if entry is None:
            return {"error": f"unknown session_id: {session_id}"}
        try:
            await entry[0].close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("session close failed: %s", exc)
        return {"closed": session_id}
