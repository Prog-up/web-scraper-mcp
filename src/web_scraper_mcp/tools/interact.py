"""Bounded persistent browser sessions on the guarded, sandboxed page pool."""

import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import origin
from ..llm import truncate_bytes
from ..runtime import pool
from ..security import parse_url


@dataclass
class Session:
    manager: AbstractAsyncContextManager
    page: Any
    expires_at: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_sessions: OrderedDict[str, Session] = OrderedDict()
_opening = 0
_reaper: asyncio.Task | None = None
logger = logging.getLogger(__name__)


async def _drop(session_id: str) -> None:
    session = _sessions.pop(session_id, None)
    if session is not None:
        await session.manager.__aexit__(None, None, None)


async def _expire() -> None:
    for sid, session in list(_sessions.items()):
        if not session.lock.locked() and session.expires_at <= time.monotonic():
            try:
                await _drop(sid)
            except Exception:
                logger.debug("expired browser session could not close")


def start_cleanup() -> None:
    global _reaper

    async def reap():
        while True:
            await asyncio.sleep(min(30, settings.browser_session_ttl_s))
            await _expire()

    if _reaper is None or _reaper.done():
        _reaper = asyncio.create_task(reap())


async def close() -> None:
    global _reaper
    if _reaper is not None:
        _reaper.cancel()
        await asyncio.gather(_reaper, return_exceptions=True)
        _reaper = None
    for sid in list(_sessions):
        try:
            await _drop(sid)
        except Exception:
            logger.debug("crashed browser session could not close")


async def _new() -> tuple[str, Session]:
    global _opening
    await _expire()
    if len(_sessions) + _opening >= min(
        settings.max_browser_sessions, settings.max_concurrent_pages
    ):
        raise ValueError("browser session capacity reached; close a session first")
    _opening += 1
    try:
        manager = pool.page()
        page = await manager.__aenter__()
        sid = uuid4().hex
        session = Session(manager, page, time.monotonic() + settings.browser_session_ttl_s)
        _sessions[sid] = session
        return sid, session
    finally:
        _opening -= 1


async def _snapshot(session_id: str, page) -> dict:
    parse_url(page.url)
    state = pool.page_state(page)
    if state.error:
        raise ValueError(state.error)
    # Limit DOM serialization and reject oversized bodies before ARIA extraction.
    fits = await page.evaluate(
        "maximum => new TextEncoder().encode(document.documentElement.outerHTML).length <= maximum",
        settings.max_response_bytes,
    )
    if not fits:
        raise ValueError("browser document exceeds byte limit")
    snapshot = await page.locator("body").aria_snapshot()
    return {
        "session_id": session_id,
        "url": page.url,
        "title": truncate_bytes(await page.title(), 4096),
        "snapshot": truncate_bytes(snapshot, settings.browser_snapshot_bytes),
        "snapshot_truncated": len(snapshot.encode()) > settings.browser_snapshot_bytes,
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def browser_navigate(
        url: Annotated[str, Field(max_length=8192)],
        session_id: Annotated[str | None, Field(max_length=64)] = None,
    ) -> dict:
        """Open a public URL in a new/reused session and return a bounded ARIA snapshot."""
        parse_url(url)
        await _expire()
        if session_id is None:
            session_id, session = await _new()
        else:
            found = _sessions.get(session_id)
            if found is None:
                return {"error": "unknown or expired session_id"}
            session = found
        if session.lock.locked():
            return {"error": "session is busy", "session_id": session_id}
        async with session.lock:
            try:
                await pool.navigate(session.page, url)
                return await _snapshot(session_id, session.page)
            except BaseException:
                await _drop(session_id)
                raise
            finally:
                session.expires_at = time.monotonic() + settings.browser_session_ttl_s

    @mcp.tool
    async def browser_act(
        session_id: Annotated[str, Field(max_length=64)],
        action: Literal["click", "fill", "press", "select", "wait"],
        selector: Annotated[str | None, Field(max_length=2048)] = None,
        value: Annotated[str | None, Field(max_length=8192)] = None,
    ) -> dict:
        """Perform an explicit action; writes are limited to the current page origin."""
        await _expire()
        session = _sessions.get(session_id)
        if session is None:
            return {"error": "unknown or expired session_id"}
        if session.lock.locked():
            return {"error": "session is busy", "session_id": session_id}
        if action != "press" and not selector:
            return {"error": "selector is required", "session_id": session_id}
        async with session.lock:
            page = session.page
            state = pool.page_state(page)
            state.write_origin = origin(page.url)
            state.allow_writes = action != "wait"
            previous_final_url = state.final_url
            try:
                async with asyncio.timeout(settings.request_timeout_s):
                    if action == "click":
                        await page.click(selector)
                    elif action == "fill":
                        await page.fill(selector, value or "")
                    elif action == "press":
                        await page.press(selector or "body", value or "Enter")
                    elif action == "select":
                        await page.select_option(selector, value or "")
                    else:
                        await page.wait_for_selector(selector)
                if (
                    state.final_url
                    and state.final_url != previous_final_url
                    and state.final_url != page.url
                ):
                    await pool.navigate(page, state.final_url)
                return await _snapshot(session_id, page)
            except asyncio.CancelledError:
                await _drop(session_id)
                raise
            except Exception as exc:
                try:
                    parse_url(page.url)
                except ValueError:
                    state.error = "page navigated outside HTTP(S)"
                if state.error or page.is_closed():
                    await _drop(session_id)
                return {
                    "error": f"{action} failed ({type(exc).__name__})",
                    "session_id": session_id,
                }
            finally:
                state.allow_writes = False
                state.write_origin = None
                session.expires_at = time.monotonic() + settings.browser_session_ttl_s

    @mcp.tool
    async def browser_close(session_id: Annotated[str, Field(max_length=64)]) -> dict:
        """Close a session and release its shared browser page capacity."""
        session = _sessions.get(session_id)
        if session is None:
            return {"error": "unknown or expired session_id"}
        if session.lock.locked():
            return {"error": "session is busy", "session_id": session_id}
        await _drop(session_id)
        return {"closed": session_id}
