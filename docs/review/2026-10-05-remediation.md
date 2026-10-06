# Remediation and feature validation — updated 6 October 2026

Work is on `codex/security-remediation`, based on `87373be62cdf1dd92d1670fa023b3cd608888fd8`.
The reviewed changes are committed as the release 1.1.0 candidate. The original [review](2026-10-05-review.md) records the
baseline; the [plan](2026-10-05-plan.md) and this document record remediation.

All **ten advertised MCP tools are implemented and regression-tested**.
Crawl, mapping and browser interaction had been deleted before the reviewed
baseline; they were restored on the hardened fetch/browser layer after the user
requested preservation of all features. The initial four-tool remediation scope
has been superseded.

## Implemented changes

| Findings | Result |
| --- | --- |
| F01–F03 | Connection-time DNS validation, approved-literal connections preserving Host/SNI/certificate checks, mixed/non-global address denial, guarded browser HTTP resources, WebSocket/service-worker blocking, and an internal-network proxy topology. |
| F04, F09, F10 | Streamed wire/decoded byte limits, total deadlines, bounded request/schema/model inputs, admission limits, bounded TTL caches, async DNS admission retained after cancellation, bounded parsing/search workers, and capped link output. Restored crawl frontiers/results/jobs and browser sessions have independent bounds. |
| F05 | HTTP refuses missing/blank bearer tokens; stdio can remain token-free. Transport-body limits precede JSON parsing. |
| F06 | Refreshed affected transitive dependencies and Playwright. PyJWT **2.15.1** and AnyIO **4.15.1** exceed requested minima. Frozen OSV audit finds zero affected packages. Debian packages refreshed without cached build layers; installed `perl-base` **5.40.1-6+deb13u1** exceeds **5.36.0-7+deb12u4**. The Docker build checks that minimum with Debian version comparison. |
| F07 | All ten tools registered. Original crawl tests restored; new feature/provider/transport/browser fixtures cover the restored functionality. README/settings match the implemented surface. |
| F08, F15 | Source checks and exact-image browser/vulnerability scans gate publication. Both browser scripts run in GitHub/GitLab image jobs. GitHub/Docker Hub is the sole release path; actions/base images pinned; signing/SPDX attestation and verification target the published digest. |
| F11 | Sandboxed Chromium enabled deliberately, default rendering disabled, user-approved modern Docker seccomp profile, non-root container, reduced capabilities, read-only filesystem and resource caps. |
| F12 | Robots enabled by default; destination policy checked on every redirect; robots failures deny access; credential headers stripped on cross-origin redirects. Same-domain crawls deny destination changes before connecting. |
| F13 | Schema and structured output validated locally; remote references/regex schemas rejected; wrong tool names and incomplete/truncated model outputs rejected. Research budgets account for JSON escaping and preserve useful text across 15 sources. |
| F14 | Non-success statuses and unsupported content rejected; delayed rendering has a bounded readiness strategy; source failures retained; research citation indices checked. Model requests use the tool deadline rather than the shorter page-fetch timeout. Ollama thinking is configurable, defaulting to false for bounded extraction/research tasks. |
| F16 | Exception-safe context/client/driver cleanup, disconnected-browser recovery, reserved session capacity, job/session expiry, cancellation, and shutdown cleanup. Browser URL stabilization preserves the actual redirect origin and SPA history changes without clearing form state. |
| F17 | Foreground launcher; runtime log removed from Git index and preserved locally; log files ignored. |
| F18 | Offline four-fixture parser scorecard regenerated with revision/dirty/dependency/fixture metadata; actual overall F1 is 0.849. |

## Feature coverage

| Feature | Verification |
| --- | --- |
| `scrape` | Title/markdown/links/raw HTML; status/content failures and render paths; real public page smoke test. |
| `search` | Tavily, Brave, SearXNG and DuckDuckGo adapters tested with controlled upstreams; default DuckDuckGo returned three live public results. |
| `extract` | Schema and freeform modes through registered MCP tools, real Anthropic SDK with controlled HTTP responses, and live Ollama `agent-pro:latest`; schema/incomplete/output-budget errors tested. |
| `deep_research` | Search/read/synthesize, source failures, citation validation, 15-source escaped-input budgeting; both providers with controlled HTTP responses; live Ollama cited report on a controlled article. |
| `crawl`, `check_crawl_status` | BFS, depth/page/domain limits, canonical deduplication, result/frontier/admission bounds, polling, cancellation, expiry, errors and shutdown; two pages crawled on the real public Python documentation site. |
| `map` | Canonical URLs, same-domain filtering, deduplication, requested link cap and byte cap; ten links returned from the real Python documentation site. |
| `browser_navigate` | New/reused sessions, ARIA snapshot, real final URL, cookie isolation, capacity, expiry, rejected-navigation cleanup. |
| `browser_act` | Click/fill/press/select/wait, multiple cookies, same-origin POST forms, redirected final origin, SPA history preserves form state; cross-origin and idle writes denied. |
| `browser_close` | Releases reserved page capacity; unclosed sessions released at server shutdown. |

All tools are exercised through registered FastMCP clients. Real subprocess stdio
and authenticated streaming HTTP integration tests roundtrip the seven
non-browser tools and verify the complete inventory. The three browser tools
also roundtrip authenticated streaming HTTP against the actual Chromium binary
inside the final sandboxed artifact. Browser fixtures use controlled broker
responses; they do not establish compatibility with arbitrary live sites.

## Validation

- **136 tests passed on each of Python 3.11.16, 3.12.15 and 3.13.14.** The older
  in-process ASGI authentication fixture was corrected to request a JSON response:
  ASGITransport can signal a premature disconnect for SSE. Actual streaming HTTP
  still runs through real local sockets in the integration suite.
- Ruff lint/format, mypy (**21 source files**), Bandit, and `git diff --check` pass.
  Compose configuration and GitHub/GitLab YAML parse successfully. Model/search
  provider, Ollama host alias, thinking and job/session settings are forwarded by
  Compose; interpolation checks retain the internal network and guarded proxy.
- OSV: all **130** locked registry packages queried; **zero affected packages**.
- Pinned Gitleaks: **29 Git commits** and current application source scanned;
  **zero leaks**. The local `.env` was not published.
- Final image: Python **3.12.15**, Playwright **1.63.0**, Chrome Headless Shell
  **153.0.8010.12**, build **1243**. Only the headless browser is installed.
- Both browser/proxy scripts pass with sandbox enabled, `--network none`, a
  read-only filesystem, bounded CPU/memory/process/tmp storage,
  `--cap-drop ALL --cap-add SYS_CHROOT`, and no-new-privileges.
- The security fixture verifies delayed DOM content, broker final URL handling,
  denied private HTTP resources, blocked WebSockets, zero service-worker
  registrations, **zero denied-fixture connections**, and actual proxy denial
  of private HTTP and HTTPS CONNECT using local sockets.
- The feature fixture runs direct MCP and authenticated streaming HTTP modes;
  verifies all actions/form/cookie/session/SPA cases above and the configured
  webdriver fingerprint mitigation.
- Live Ollama version **0.35.1**, `agent-pro:latest` (Qwen 3.5 9B family):
  structured product extraction returned the expected name, brand and price;
  freeform extraction returned the name and price; research returned the
  expected material/warranty with valid source citations. Thinking enabled by
  the model default initially caused HTTP 499 in one freeform request. All three
  modes passed after disabling thinking and separating model/fetch deadlines.
- A later attempt combining live public pages and live Ollama hit connection
  timeouts; a direct endpoint recheck also timed out. Public map/crawl succeeded
  in that run. This demonstrates the earlier model success, not continuous
  availability of the user's endpoint. Paid provider credentials were absent;
  Anthropic/Brave/Tavily were validated against controlled adapters only.

Reproduce the browser checks after building:

```bash
docker build --pull --no-cache -t web-scraper-mcp:review .
for fixture in scripts/browser_regression.py scripts/browser_features.py; do
  docker run --rm -i --init --network none --read-only \
    --tmpfs /tmp:size=256m --shm-size=256m --memory=1536m --cpus=2 --pids-limit=256 \
    --cap-drop ALL --cap-add SYS_CHROOT --security-opt no-new-privileges:true \
    --security-opt seccomp=deploy/chromium-seccomp.json \
    web-scraper-mcp:review python - < "$fixture"
done
```

## Release blockers and remaining acceptance work

**At this review snapshot, the full vulnerability scan blocked release.** Despite
a fresh Debian 13.7 package update, Trivy reports **59 HIGH and one CRITICAL package findings**, covering
**22 distinct CVEs**, with no fixed Debian versions listed. The critical finding
is `CVE-2026-6653` in `libxml2`. Removing its Mesa dependency chain also removed
`libgbm`, which Chromium needs; the working dependency chain is retained.
Unused X server, Vulkan and printing packages were removed.

The [artifact evidence](2026-10-05-remediation-evidence.json) records exact source,
lockfile and image identities and every remaining HIGH/CRITICAL finding. Local
and image source/lockfile hashes matched at the recorded pre-release validation;
the subsequent package-version bump is tracked in [the release candidate](../releases/1.1.0.md). No blanket waiver, `ignore-unfixed`, or
nonblocking release scan was added. Publication waits for patched packages or
narrowly reviewed, owned, expiring applicability decisions. Python, Node and uv
inventories had no HIGH/CRITICAL findings in the scan; this does not prove every
bundled browser binary is vulnerability-free.

Before deployment:

1. Run hosted pipelines on a clean committed checkout. The complete supported
   Python matrix passed locally; no remote workflow was triggered, image pushed,
   signature issued, or registry attestation verified during this task.
2. Review host firewall/network policy. Docker `internal` blocks ordinary
   external routing but permits host services on the bridge address. Stronger
   containment against a compromised browser needs host-bound filtering or an
   isolated gateway with separate ingress. See [Docker gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes).
3. Ensure trusted model/search endpoints remain reachable from the deployment
   network and run acceptance checks with the actual provider credentials.
   Compose does not provision a model server. Citation indices do not prove
   factual support; prompt framing does not guarantee prompt-injection immunity.
4. Measure peak memory and responsiveness with representative adversarial
   pages and concurrent clients. Cancelled threads retain capacity until their
   work finishes. Whole-service resource sizing requires deployment validation.
5. Expand parser/render/model quality fixtures, particularly listings and real
   JavaScript sites. Per-client quotas and multi-tenant isolation remain future
   product work; one bearer token shares all jobs and browser sessions.

The user explicitly approved the seccomp replacement and sandbox tests after
automatic approval review initially rejected the persistent policy change.
[Profile provenance](../../deploy/README.md) records its upstream commit and
existing namespace allowance. User-owned untracked experiments/text files and
the original Trivy report were preserved. Local `server.log` remains on disk.
The implementation and candidate metadata were committed on the review branch.
The user subsequently explicitly approved the scoped 1.1.0 exception on 6 October
2026; see [release notes](../releases/1.1.0.md) for its exact inventory and expiry.
