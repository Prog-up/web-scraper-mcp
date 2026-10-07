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


def test_crawl_seed_failure(monkeypatch):
    async def _failing_crawl_one(url, same_domain):
        raise ValueError("Connection refused")

    monkeypatch.setattr(crawlmod, "_crawl_one", _failing_crawl_one)
    job = crawlmod.CrawlJob(job_id="t4")
    asyncio.run(crawlmod._run(job, "https://s/a", max_pages=100, max_depth=5, same_domain=True))
    assert job.status == "failed"
    assert "Failed to fetch seed URL (ValueError)" == job.error


async def test_bounded_batches_preserve_bfs_order_and_page_cap(monkeypatch):
    """A fast sibling cannot reorder results or start more pages than requested."""
    monkeypatch.setattr(crawlmod.settings, "crawl_concurrency", 3)
    monkeypatch.setattr(crawlmod.settings, "max_concurrent_fetches", 2)
    second_started = asyncio.Event()
    active = peak = 0
    visited = []

    async def fetch(url, same_domain):
        nonlocal active, peak
        visited.append(url)
        active += 1
        peak = max(peak, active)
        try:
            if url == "https://s/b":
                await second_started.wait()
            elif url == "https://s/c":
                second_started.set()
            return await _fake_crawl_one(url, same_domain)
        finally:
            active -= 1

    monkeypatch.setattr(crawlmod, "_crawl_one", fetch)
    job = crawlmod.CrawlJob(job_id="batch")
    async with asyncio.timeout(2):
        await crawlmod._run(job, "https://s/a", max_pages=3, max_depth=5, same_domain=True)
    assert job.status == "completed"
    assert [page["url"] for page in job.pages] == ["https://s/a", "https://s/b", "https://s/c"]
    assert visited == ["https://s/a", "https://s/b", "https://s/c"]
    assert peak == 2 and active == 0


async def test_cancellation_awaits_all_batch_children_and_keeps_partial_pages(monkeypatch):
    monkeypatch.setattr(crawlmod.settings, "crawl_concurrency", 3)
    monkeypatch.setattr(crawlmod.settings, "max_concurrent_fetches", 3)
    entered = asyncio.Event()
    active = 0
    cleaned = set()

    async def fetch(url, same_domain):
        nonlocal active
        if url == "https://s/a":
            return {"url": url, "markdown": "seed"}, [f"https://s/{i}" for i in range(3)]
        active += 1
        if active == 3:
            entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            # Cleanup itself yields, so merely sending cancellation is insufficient.
            await asyncio.sleep(0)
            cleaned.add(url)
            active -= 1

    monkeypatch.setattr(crawlmod, "_crawl_one", fetch)
    job = crawlmod.CrawlJob(job_id="cancel-batch")
    task = asyncio.create_task(crawlmod._run(job, "https://s/a", 100, 5, True))
    async with asyncio.timeout(2):
        await entered.wait()
        task.cancel()
        await task
    assert job.status == "cancelled"
    assert [page["url"] for page in job.pages] == ["https://s/a"]
    assert active == 0 and len(cleaned) == 3


async def test_batch_failures_redirect_dedup_and_result_budget(monkeypatch):
    monkeypatch.setattr(crawlmod.settings, "crawl_concurrency", 3)
    monkeypatch.setattr(crawlmod.settings, "max_concurrent_fetches", 3)
    monkeypatch.setattr(crawlmod.settings, "crawl_result_bytes", 1024)

    async def fetch(url, same_domain):
        if url == "https://s/a":
            return {"url": url, "markdown": "seed"}, [
                "https://s/b",
                "https://s/c",
                "https://s/missing",
                "https://s/huge",
            ]
        if url.endswith("missing"):
            raise ValueError("unavailable")
        if url.endswith("huge"):
            return {"url": url, "markdown": "x" * 1024}, []
        return {"url": "https://s/final", "markdown": "same redirected page"}, []

    monkeypatch.setattr(crawlmod, "_crawl_one", fetch)
    job = crawlmod.CrawlJob(job_id="batch-budget")
    await crawlmod._run(job, "https://s/a", 100, 1, True)
    assert job.status == "completed" and job.truncated
    assert [page["url"] for page in job.pages] == ["https://s/a", "https://s/final"]
    assert len(job.failures) == 1
    assert job.result_bytes <= 1024


async def test_two_crawls_share_server_worker_capacity(monkeypatch):
    monkeypatch.setattr(crawlmod.settings, "crawl_concurrency", 3)
    monkeypatch.setattr(crawlmod.settings, "max_concurrent_fetches", 2)
    active = peak = 0

    async def fetch(url, same_domain):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return await _fake_crawl_one(url, same_domain)
        finally:
            active -= 1

    monkeypatch.setattr(crawlmod, "_crawl_one", fetch)
    jobs = [crawlmod.CrawlJob(job_id=str(i)) for i in range(2)]
    await asyncio.gather(*(crawlmod._run(job, "https://s/a", 4, 5, True) for job in jobs))
    assert peak == 2 and active == 0
    assert all(job.status == "completed" and len(job.pages) == 4 for job in jobs)
    assert all(not job.failures for job in jobs)
