"""Renderer never continues unchecked network requests; setup is exception safe."""

from types import SimpleNamespace

import pytest

from web_scraper_mcp import fetch as fm
from web_scraper_mcp.browser import BrowserPool, PageState
from web_scraper_mcp.config import Settings


class Page:
    def __init__(self):
        self.main_frame = SimpleNamespace(page=self)


class Route:
    def __init__(self, page, url="https://public.example/", method="GET"):
        self.request = SimpleNamespace(
            url=url,
            method=method,
            headers={},
            frame=page.main_frame,
            is_navigation_request=lambda: True,
        )
        self.aborted = False
        self.fulfilled = None

    async def abort(self):
        self.aborted = True

    async def continue_(self):
        pytest.fail("unchecked browser networking must never be continued")

    async def fulfill(self, **kwargs):
        self.fulfilled = kwargs


async def test_browser_redirects_are_resolved_by_guarded_broker(monkeypatch):
    page = Page()
    pool = BrowserPool(Settings(_env_file=None))
    pool._pages[page] = PageState()

    async def request(url, s, **kwargs):
        return fm.HTTPResult(
            "https://final.example/article",
            200,
            {"content-type": "text/html"},
            b"<html><body>article</body></html>",
        )

    monkeypatch.setattr(fm, "request_http", request)
    route = Route(page)
    await pool._guard_route(route)
    assert route.fulfilled["status"] == 200
    assert b'<base href="https://final.example/article">' in route.fulfilled["body"]
    assert pool.page_state(page).final_url == "https://final.example/article"


async def test_broker_rejection_aborts_navigation(monkeypatch):
    page = Page()
    pool = BrowserPool(Settings(_env_file=None))
    pool._pages[page] = PageState()

    async def denied(*args, **kwargs):
        raise fm.BlockedURLError("private destination")

    monkeypatch.setattr(fm, "request_http", denied)
    route = Route(page)
    await pool._guard_route(route)
    assert route.aborted and not route.fulfilled
    assert pool.page_state(page).error


async def test_browser_context_closed_on_new_page_failure(monkeypatch):
    class Context:
        closed = False

        async def route(self, *args):
            pass

        async def route_web_socket(self, *args):
            pass

        async def new_page(self):
            raise RuntimeError("page failed")

        async def close(self):
            self.closed = True

    context = Context()

    class Browser:
        async def new_context(self, **kwargs):
            assert kwargs["service_workers"] == "block"
            assert kwargs["accept_downloads"] is False
            return context

    pool = BrowserPool(Settings(_env_file=None))

    async def ensure():
        return Browser()

    monkeypatch.setattr(pool, "_ensure", ensure)
    with pytest.raises(RuntimeError, match="page failed"):
        async with pool.page():
            pass
    assert context.closed
    assert pool._slots.active == 0


async def test_render_fails_closed_without_guarded_proxy():
    pool = BrowserPool(Settings(_env_file=None, browser_enabled=True, egress_proxy_url=None))
    with pytest.raises(RuntimeError, match="isolated guarded proxy"):
        await pool._ensure()
