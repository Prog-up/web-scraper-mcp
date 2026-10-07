# MCP tool verification and built-in comparison

Date: 2026-10-07. Branch: `codex/tool-efficiency-review`, based on
`66fcaa815b1b145b3030f79735c75d1a981176db`.
Tested package source SHA-256:
`51249faefa219b1f0188b0779224658f6f792f8fd9e3f8b0af898d7bed18f923`.

All ten registered tools passed their applicable functional checks. Live public
fetch/search/crawl/model calls passed with `agent-fast-132K:latest`. Browser
features passed against controlled pages in the hardened container, through
in-process and authenticated HTTP MCP. This establishes the tested contracts,
not universal compatibility with every website or model.

These changes are on this branch. The published Docker Hub 1.1.0 image contains
the earlier implementation; publishing the fixes requires a subsequent release.

## Fixes made

- Crawl: replace serial traversal with bounded batches, default three workers.
  Preserve discovery order, depth/page/frontier/result limits, redirect checks,
  cancellation cleanup, and partial results. Share a worker semaphore across
  admitted jobs, bounded by fetch and blocking-work capacity. Deduplicate final
  URLs before charging result bytes. `SCRAPER_CRAWL_CONCURRENCY=1` restores serial
  operation; values 1–8 are accepted.
- Scrape/parser: remove navigation and direct body header/footer/aside chrome
  before short-page fallback. Preserve headers inside articles and short product
  listings. This also benefits crawl, extraction and research inputs.
- Extract: Ollama previously ignored an extraction tool declaration and returned
  prose. Send JSON Schema in `format` and in task instructions, set temperature
  zero, and continue validating locally. Account for both schema copies in input
  budgets. Keep Anthropic's forced tool output and backward-compatible parsing
  of legacy Ollama tool responses.
- Research: supply concrete allowed citation numbers and request a concise report.
  Reject literal `[n]` placeholders even when a valid numeric citation also
  appears. Keep missing/out-of-range citation and truncation rejection.
- Add `benchmarks/tools.py` for reproducible MCP-level fixture/live diagnostics.
  It records failures, output sizes, source hash and timings without credentials.

Ollama documents JSON Schema in `format`, local validation, and including the
schema in the prompt in its [structured-output guide](https://docs.ollama.com/capabilities/structured-outputs).

The ignored local `.env` selects `agent-fast-132K:latest` for both model tools and
`SCRAPER_OLLAMA_NUM_CTX=131072`, matching the model's configured context. The
server's separate input cap remains 16,000 UTF-8 bytes, reserving space for task,
schema and framing; the context setting does not imply 131,072 tokens of source
text are sent. Output remains capped at 2,048 tokens; thinking is disabled.
These local settings and the private model endpoint are excluded from Git.

## Tool-by-tool verification and comparison

"Built-in" below means tools exposed in this Codex session: `web.run` and the
in-app browser via `cua_repl`. API documentation is supporting context, not a
promise that every OpenAI product exposes the same interface.

| MCP tool | Verification | Closest built-in capability and practical difference |
| --- | --- | --- |
| `scrape` | Live Python and Playwright docs; title, Markdown, optional HTML/links; static/rendered paths and fetch policy tests | Web open returns bounded source excerpts and references, with follow-up open/find. MCP returns a predictable bounded Markdown response for downstream processing. |
| `crawl` | Live three-page crawl; fixture 13-page crawl; BFS order, dedup, caps, redirects, failed sources, two concurrent jobs | No exposed built-in background crawl job. Built-in search/open can discover/read pages with orchestration; MCP supplies explicit page/depth bounds and job IDs. |
| `check_crawl_status` | Completion, cancellation with partial results, child cleanup, expiry and shutdown tests | No equivalent crawl-status endpoint. MCP makes background progress/cancellation explicit. |
| `map` | Live ten-link map; canonical dedup, same-host and result caps | Built-in browser can inspect page links through DOM locators; web open also exposes references. MCP provides a dedicated canonical URL list. |
| `browser_navigate` | Session creation/reuse, redirects, delayed DOM, cookie isolation and ARIA snapshot | Built-in browser supplies persistent tabs, semantic DOM/ARIA access and screenshots. MCP offers bounded server-owned sessions with public-destination/egress controls. |
| `browser_act` | Click, fill, press, select, wait; same-origin form POST; SPA history; deny cross-origin/idle writes | Built-in browser offers semantic role/label locators, frames, checkboxes, screenshots and richer interaction. MCP's smaller selector/action contract is easier to integrate programmatically. No browser speed ranking was established. |
| `browser_close` | Page capacity released; session limits, idle expiry and shutdown | Built-in tab close supplies similar lifecycle control. MCP additionally accounts for reserved server page capacity. |
| `search` | Live DuckDuckGo results; mocked Tavily, Brave and SearXNG adapters and priority/error handling | Built-in web search supplies source references and supports richer research workflows. MCP selects the configured provider by priority and returns a capped normalized result list. |
| `extract` | Live schema and text extraction; Ollama/Anthropic SDK fixtures; invalid schema/output, non-object schema and input-budget tests | Built-in model plus web/browser can extract data, but this session has no equivalent one-call arbitrary-JSON-Schema web extraction tool. MCP validates shape locally and allows a self-hosted model. This does not prove factual accuracy or equal model quality. |
| `deep_research` | Live two-source reports; source failures, model truncation and invalid citations tested | Built-in search/open/find plus model synthesis supports flexible sourced research. MCP packages a bounded search/read/synthesis pipeline with explicit source failures and citation-index checks. Neither citation syntax nor a valid source index proves factual support. |

The built-in browser was also exercised directly: open the Playwright locators
page, inspect accessibility state, click the `Mock APIs` link by role/name,
verify the destination and close the temporary tab. The OpenAI
[web-search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
documents source citations, search/open/find actions and filtering capabilities
for its API tool; the table uses this session's actually exposed tools.

## Measured efficiency

All durations are wall-clock seconds. These are small diagnostics, not service
SLAs or a statistically representative quality/speed contest.

| Matched URL/query | MCP seconds | Built-in web seconds | Samples |
| --- | ---: | ---: | --- |
| Python documentation index | 1.044 | 2.089 | 2 per system, median |
| Python asyncio tasks documentation | 1.110 | 2.138 | 2 per system, median |
| Playwright locators documentation | 1.143 | 1.740 | 2 per system, median |
| Python asyncio TaskGroup documentation search | 1.525 | 1.848 | MCP 1; built-in 2, median |

MCP scrape included capped links and returned roughly 5.5–49.5 KB of structured
output. Built-in web calls requested short responses with references; their
content and infrastructure differ. Calls were sequential, not interleaved or
cache-controlled. MCP was quicker in these samples; a general speed claim or
quality ranking would require a larger matched workload. We did not benchmark
built-in browser actions or full built-in research against Ollama inference.

| Server measurement | Result | Scope |
| --- | ---: | --- |
| 13-page fixture crawl, one worker | 1.004 s median | 5 completions; 50 ms mocked fetch/page |
| Same crawl, three workers | 0.478 s median | 5 completions; peak 3 fetches; about 2.10× faster |
| Live three-page crawl | 3.095 s | One completion; robots and domain pacing enabled |
| Live map, ten links | 0.050 s | One call after earlier reads; warm policy/DNS state possible |
| Crawl status / cancellation | 0.004 / 0.004 s | One live call each; cancellation before pages completed |
| Live structured / text extract | 2.657 / 1.166 s | One call each; selected 132K model |
| Live two-source research | 38.763 s | One call; selected 132K model; no source failures |

The serial and parallel fixture runs were executed sequentially to avoid competing
with each other for CPU. They mock HTTP and model providers and therefore do not
measure DNS, TLS or inference time. Live site pacing still limits crawl throughput.

Provider/model calls dominate research latency. A second live research query
also returned a report with valid indices, but omitted exception-handling nuance
when manually inspected. The quality checks do not establish comprehensive
factual accuracy. A larger context setting alone does not remove the separate
source-input cap or guarantee a better answer.

Offline parser token-F1 on the four bundled page fixtures:

| Page type | Before | After |
| --- | ---: | ---: |
| Article | 1.000 | 1.000 |
| Forum | 0.949 | 0.949 |
| Product | 0.945 | 1.000 |
| Listing | 0.500 | 1.000 |
| Overall | 0.849 | 0.987 |

This is a fixture-specific improvement, not a real-web accuracy estimate. Peak
RSS in the tool harness includes Python/import/test overhead; no memory-efficiency
claim is made from these runs.

## Validation and evidence

- Python 3.11, 3.12, 3.13: **162 passed** on each. The suite covers real localhost
  HTTP and stdio subprocess MCP round trips as well as controlled upstreams.
- Ruff lint/format, mypy and Bandit: passed; no Bandit issues reported.
- Both Chromium regression scripts passed using released runtime image ID
  `sha256:b60489a4a9af824077f44a0f9ac032173f5a4f8f9bd041c629141fdfa109a026`
  with this branch's package mounted read-only. Network disabled, non-root,
  read-only filesystem, approved seccomp, no-new-privileges and resource limits
  remained enabled. This tests changed source in the released runtime, not a
  newly built or published image.
- Sandbox active; private HTTP, WebSocket and service-worker requests blocked;
  denied fixture endpoint received zero requests; guarded HTTP/CONNECT proxy
  denials passed. Browser suites passed in-process and authenticated HTTP.
- Live paid API calls were not made. Anthropic/Tavily/Brave behavior was tested
  with controlled provider responses. Public-site CAPTCHA/paywall/anti-bot
  bypass and arbitrary authenticated websites are outside these checks.

Raw measurements: [live](2026-10-07-tool-measurements/live-agent-fast-132K.json),
[serial fixture](2026-10-07-tool-measurements/fixture-serial.json),
[parallel fixture](2026-10-07-tool-measurements/fixture-parallel.json),
[parser before](2026-10-07-tool-measurements/parser-before.json),
[parser after](2026-10-07-tool-measurements/parser-after.json),
[built-in calls](2026-10-07-built-in-measurements.json).
Live measurements predate the benchmark harness's added crawl repetition loop;
their single crawl completion is reported as one sample.

Reproduce fixture timings:

```sh
SCRAPER_CRAWL_CONCURRENCY=1 uv run python benchmarks/tools.py --mode fixture --samples 5 --output /tmp/serial.json
uv run python benchmarks/tools.py --mode fixture --samples 5 --output /tmp/parallel.json
```

Live mode uses configured Ollama and search services, reads public documentation
and refuses configured paid API keys:

```sh
uv run python benchmarks/tools.py --mode live --samples 2 --output /tmp/live.json
```

The browser scripts require the hardened container settings described in
`deploy/README.md`; they deliberately trigger rejected-navigation errors while
asserting cleanup and isolation.

## Follow-up plan

1. Review this branch and run the existing quality/security workflows before a
   subsequent release. Verify the resulting immutable image and rerun sandbox
   regressions; this review does not extend the earlier 1.1.0 CVE exception.
2. Add a broader held-out corpus: real listings/forums, JavaScript pages,
   extraction schemas and research questions with claim-level expected evidence.
   Measure content completeness, factual support and cold/warm latency separately.
3. Tune Ollama's input/context/output budgets using that corpus and actual host
   memory/latency measurements. Increase source-input bytes only if gains justify
   the added inference cost; retain admission limits and total deadlines.
4. Use this MCP for predictable Markdown, canonical maps, bounded crawl jobs and
   local-model extraction. Use built-in web tools for flexible cited research and
   the built-in browser for richer visual or semantic interactions.
