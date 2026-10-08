"""Bounded background BFS jobs, polling/cancellation, expiry and shutdown cleanup."""

import asyncio
import json
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Annotated
from uuid import uuid4

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import canonical_url, extract_links, same_host, title_of, to_markdown
from ..runtime import pool
from ..work import work


@dataclass
class CrawlJob:
    job_id: str
    status: str = "running"
    pages: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False
    result_bytes: int = 0
    expires_at: float = float("inf")
    task: asyncio.Task | None = field(default=None, repr=False)


_jobs: OrderedDict[str, CrawlJob] = OrderedDict()
_tasks: set[asyncio.Task] = set()
_reaper: asyncio.Task | None = None
_worker_slots: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None


def _workers() -> asyncio.Semaphore:
    """Share bounded workers across admitted jobs; no whole-frontier wait queues."""
    global _worker_slots
    loop = asyncio.get_running_loop()
    if _worker_slots is None or _worker_slots[0] is not loop:
        _worker_slots = (
            loop,
            asyncio.Semaphore(min(settings.max_concurrent_fetches, work.maximum)),
        )
    return _worker_slots[1]


async def _crawl_one(url: str, same_domain: bool) -> tuple[dict, list[str]]:
    result = await fetch(
        url,
        render=False,
        settings=settings,
        pool=pool,
        allowed_host=url if same_domain else None,
    )
    page = {
        "url": result.url,
        "title": await work.run(title_of, result.html),
        "markdown": await work.run(to_markdown, result.html, result.url),
    }
    # Filter relative to the original seed in _run, including redirects.
    links = await work.run(extract_links, result.html, result.url)
    return page, links


async def _run(
    job: CrawlJob, start: str, max_pages: int, max_depth: int, same_domain: bool
) -> None:
    try:
        async with asyncio.timeout(settings.crawl_timeout_s):
            seed = canonical_url(start)
            seen = {seed}
            frontier = deque([(seed, 0)])
            attempts = 0
            completed_urls: set[str] = set()
            concurrency = min(settings.crawl_concurrency, settings.max_concurrent_fetches)
            workers = _workers()

            async def read(url: str):
                async with workers:
                    return await _crawl_one(url, same_domain)

            while frontier and len(job.pages) < max_pages:
                remaining = min(
                    max_pages - len(job.pages), settings.crawl_frontier_limit - attempts
                )
                if remaining <= 0:
                    job.truncated = True
                    break
                batch = [
                    frontier.popleft() for _ in range(min(concurrency, remaining, len(frontier)))
                ]
                attempts += len(batch)
                # gather preserves discovery order and cancels/awaits children when
                # the parent job is cancelled. Never create the whole frontier's tasks.
                results = await asyncio.gather(
                    *(read(url) for url, _ in batch), return_exceptions=True
                )
                stop = False
                for (url, depth), result in zip(batch, results, strict=True):
                    if isinstance(result, asyncio.CancelledError):
                        raise result
                    try:
                        if isinstance(result, BaseException):
                            raise result
                        page, links = result
                        final = canonical_url(page["url"])
                        if same_domain and not same_host(final, seed):
                            raise ValueError("redirect left seed host")
                    except Exception as exc:
                        if depth == 0:
                            job.status = "failed"
                            job.error = f"Failed to fetch seed URL ({type(exc).__name__})"
                            return
                        failure = {"url": url, "error": "page failed fetch/destination policy"}
                        size = len(json.dumps(failure).encode())
                        if job.result_bytes + size <= settings.crawl_result_bytes:
                            job.failures.append(failure)
                            job.result_bytes += size
                        else:
                            job.truncated = True
                            stop = True
                            break
                        continue
                    if final in completed_urls:
                        continue
                    size = len(json.dumps(page, ensure_ascii=False).encode())
                    if job.result_bytes + size > settings.crawl_result_bytes:
                        job.truncated = True
                        stop = True
                        break
                    job.pages.append(page)
                    completed_urls.add(final)
                    job.result_bytes += size
                    seen.add(final)
                    if depth >= max_depth:
                        continue
                    for link in links:
                        try:
                            target = canonical_url(link)
                            if same_domain and not same_host(target, seed):
                                continue
                        except ValueError:
                            continue
                        if target in seen:
                            continue
                        if len(seen) >= settings.crawl_frontier_limit:
                            job.truncated = True
                            break
                        seen.add(target)
                        frontier.append((target, depth + 1))
                if stop or attempts >= settings.crawl_frontier_limit:
                    job.truncated = True
                    break
            job.status = "completed"
    except asyncio.CancelledError:
        job.status = "cancelled"
    except TimeoutError:
        job.status = "failed"
        job.error = "crawl exceeded total deadline"
    except Exception:
        job.status = "failed"
        job.error = "crawl failed"
    finally:
        job.expires_at = time.monotonic() + settings.crawl_ttl_s


def _expire() -> None:
    for key, job in list(_jobs.items()):
        if job.status != "running" and job.expires_at <= time.monotonic():
            del _jobs[key]


def start_cleanup() -> None:
    global _reaper

    async def reap():
        while True:
            await asyncio.sleep(min(30, settings.crawl_ttl_s))
            _expire()

    if _reaper is None or _reaper.done():
        _reaper = asyncio.create_task(reap())


async def close() -> None:
    global _reaper, _worker_slots
    tasks = list(_tasks)
    if _reaper is not None:
        tasks.append(_reaper)
        _reaper = None
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _tasks.clear()
    _jobs.clear()
    _worker_slots = None


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def crawl(
        url: Annotated[str, Field(max_length=8192, description="Seed URL.")],
        max_pages: Annotated[int, Field(ge=1, le=1000)] = 20,
        max_depth: Annotated[int, Field(ge=0, le=10)] = 2,
        same_domain: bool = True,
    ) -> dict:
        """Start a bounded background crawl; poll check_crawl_status for results."""
        seed = canonical_url(url)
        _expire()
        if sum(job.status == "running" for job in _jobs.values()) >= settings.max_concurrent_crawls:
            return {"error": "crawl capacity reached; retry later"}
        if len(_jobs) >= settings.max_crawl_jobs:
            finished = next((key for key, job in _jobs.items() if job.status != "running"), None)
            if finished is None:
                return {"error": "crawl job capacity reached"}
            del _jobs[finished]
        job = CrawlJob(uuid4().hex)
        _jobs[job.job_id] = job
        job.task = asyncio.create_task(
            _run(
                job,
                seed,
                min(max_pages, settings.max_crawl_pages),
                min(max_depth, settings.max_crawl_depth),
                same_domain,
            )
        )
        _tasks.add(job.task)
        job.task.add_done_callback(_tasks.discard)
        return {"job_id": job.job_id, "status": job.status}

    @mcp.tool
    async def check_crawl_status(
        job_id: Annotated[str, Field(max_length=64)],
        include_pages: bool = True,
        cancel: bool = False,
    ) -> dict:
        """Poll a crawl; set cancel=true to stop it and retain partial results."""
        _expire()
        job = _jobs.get(job_id)
        if job is None:
            return {"error": "unknown or expired job_id"}
        if cancel and job.status == "running" and job.task:
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            if job.status == "running":
                job.status = "cancelled"
                job.expires_at = time.monotonic() + settings.crawl_ttl_s
        out = {
            "job_id": job.job_id,
            "status": job.status,
            "pages_crawled": len(job.pages),
            "error": job.error,
            "truncated": job.truncated,
            "failures": job.failures,
        }
        if include_pages and job.status != "running":
            out["pages"] = job.pages
        return out
