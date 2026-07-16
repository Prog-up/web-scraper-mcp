"""crawl — multi-page BFS as a background job, polled via check_crawl_status.

ponytail: in-memory job store, fine for one user; swap for Redis only if you run
multiple workers. Job count is capped to avoid unbounded memory.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Annotated
from uuid import uuid4

from fastmcp import FastMCP
from pydantic import Field

from ..config import settings
from ..fetch import fetch
from ..parse import extract_links, title_of, to_markdown
from ..runtime import pool

_MAX_JOBS = 50


@dataclass
class CrawlJob:
    job_id: str
    status: str = "running"  # running | completed | failed
    pages: list[dict] = field(default_factory=list)
    error: str | None = None


_jobs: dict[str, CrawlJob] = {}
_tasks: set[asyncio.Task] = set()


async def _crawl_one(url: str, same_domain: bool) -> tuple[dict, list[str]]:
    """Fetch + parse one page. Isolated so tests can monkeypatch it."""
    result = await fetch(url, render=False, settings=settings, pool=pool)
    page = {
        "url": result.url,
        "title": title_of(result.html),
        "markdown": to_markdown(result.html, result.url),
    }
    links = extract_links(result.html, result.url, same_domain=same_domain)
    return page, links


async def _run(
    job: CrawlJob, start: str, max_pages: int, max_depth: int, same_domain: bool
) -> None:
    try:
        # Visit the seed URL first to detect initial validation / reachability failures
        try:
            res = await _crawl_one(start, same_domain)
        except Exception as exc:
            job.status = "failed"
            job.error = f"Failed to fetch seed URL: {exc}"
            return

        page, links = res
        job.pages.append(page)

        seen: set[str] = {start}
        frontier: list[str] = []
        for link in links:
            if link not in seen:
                seen.add(link)
                frontier.append(link)

        sem = asyncio.Semaphore(settings.max_concurrent_pages)

        async def visit(u: str) -> tuple[dict, list[str]] | None:
            async with sem:
                try:
                    return await _crawl_one(u, same_domain)
                except Exception:  # noqa: BLE001 - skip unreachable/blocked sub-pages
                    return None

        # Run the BFS loop for the remaining depth (seed page is already fetched, which is depth 0)
        for _ in range(max_depth):
            if not frontier or len(job.pages) >= max_pages:
                break
            batch = frontier[: max_pages - len(job.pages)]
            results = await asyncio.gather(*(visit(u) for u in batch))
            next_frontier: list[str] = []
            for r in results:
                if r is None:
                    continue
                p, lks = r
                job.pages.append(p)
                for link in lks:
                    if link not in seen:
                        seen.add(link)
                        next_frontier.append(link)

            frontier = next_frontier
        job.status = "completed"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc)


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def crawl(
        url: Annotated[str, Field(description="Seed URL to crawl from.")],
        max_pages: Annotated[int, Field(description="Max pages to fetch.", ge=1, le=1000)] = 20,
        max_depth: Annotated[int, Field(description="Max link depth from seed.", ge=0, le=10)] = 2,
        same_domain: Annotated[bool, Field(description="Stay on the seed's host.")] = True,
    ) -> dict:
        """Start a crawl job. Returns a job_id; poll check_crawl_status for results."""
        if len(_jobs) >= _MAX_JOBS:  # evict oldest finished job
            for jid, j in list(_jobs.items()):
                if j.status != "running":
                    del _jobs[jid]
                    break
        job = CrawlJob(job_id=uuid4().hex)
        _jobs[job.job_id] = job
        task = asyncio.create_task(
            _run(
                job,
                url,
                min(max_pages, settings.max_crawl_pages),
                min(max_depth, settings.max_crawl_depth),
                same_domain,
            )
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return {"job_id": job.job_id, "status": job.status}

    @mcp.tool
    async def check_crawl_status(
        job_id: Annotated[str, Field(description="job_id returned by crawl.")],
        include_pages: Annotated[
            bool, Field(description="Include page markdown when finished.")
        ] = True,
    ) -> dict:
        """Poll a crawl job. Pages are returned once status is completed/failed."""
        job = _jobs.get(job_id)
        if job is None:
            return {"error": f"unknown job_id: {job_id}"}
        out: dict = {
            "job_id": job.job_id,
            "status": job.status,
            "pages_crawled": len(job.pages),
            "error": job.error,
        }
        if include_pages and job.status != "running":
            out["pages"] = job.pages
        return out
