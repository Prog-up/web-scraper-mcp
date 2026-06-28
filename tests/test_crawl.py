"""Crawl BFS logic — dedup + max-pages cap. Monkeypatches the fetch step (no network)."""

import asyncio

from web_scraper_mcp.tools import crawl as crawlmod

# Small link graph with a self-link and back-links to exercise dedup.
GRAPH = {
    "https://s/a": ["https://s/b", "https://s/c", "https://s/a"],
    "https://s/b": ["https://s/a", "https://s/d"],
    "https://s/c": ["https://s/d"],
    "https://s/d": [],
}


async def _fake_crawl_one(url, same_domain):  # noqa: ANN001
    return {"url": url, "title": url, "markdown": f"# {url}"}, GRAPH.get(url, [])


def test_crawl_dedup_visits_each_once(monkeypatch):
    monkeypatch.setattr(crawlmod, "_crawl_one", _fake_crawl_one)
    job = crawlmod.CrawlJob(job_id="t1")
    asyncio.run(crawlmod._run(job, "https://s/a", max_pages=100, max_depth=5, same_domain=True))
    urls = [p["url"] for p in job.pages]
    assert job.status == "completed"
    assert len(urls) == len(set(urls))
    assert set(urls) == set(GRAPH)


def test_crawl_respects_max_pages(monkeypatch):
    monkeypatch.setattr(crawlmod, "_crawl_one", _fake_crawl_one)
    job = crawlmod.CrawlJob(job_id="t2")
    asyncio.run(crawlmod._run(job, "https://s/a", max_pages=2, max_depth=5, same_domain=True))
    assert len(job.pages) == 2


def test_crawl_depth_zero_is_seed_only(monkeypatch):
    monkeypatch.setattr(crawlmod, "_crawl_one", _fake_crawl_one)
    job = crawlmod.CrawlJob(job_id="t3")
    asyncio.run(crawlmod._run(job, "https://s/a", max_pages=100, max_depth=0, same_domain=True))
    assert [p["url"] for p in job.pages] == ["https://s/a"]
