# Web Scraper MCP

A self-hosted MCP server with ten tools for scraping, crawling, mapping, search,
extraction, research, and persistent browser interaction. Python 3.11–3.13 is supported.

## Tools

| Tool | Behavior |
| --- | --- |
| `scrape` | Fetch one public URL and return title, markdown, and optional capped links. |
| `crawl` | Start a bounded background crawl with page/depth caps and optional same-host policy. |
| `check_crawl_status` | Poll results or set `cancel=true` to stop a job and retain partial results. |
| `map` | Return canonical, deduplicated links; defaults to the source host. |
| `browser_navigate` | Open a new browser session or reuse a `session_id`; return an ARIA snapshot. |
| `browser_act` | Click, fill, press, select, or wait using a selector; explicit actions can make same-origin writes. |
| `browser_close` | Close a session and release its reserved page capacity. |
| `search` | Search with Tavily, Brave, SearXNG, or DuckDuckGo, in that priority order. |
| `extract` | Fetch a page and ask Anthropic or Ollama for structured data or text. Structured results are validated locally. |
| `deep_research` | Search, read bounded sources, and synthesize a report with checked citation indices and explicit source failures. |

Fetching is static by default. Browser rendering requires explicit configuration,
a sandbox-compatible host, and an isolated guarded proxy. Error status pages and
unsupported content types are rejected rather than used as successful sources.

## Run locally

```bash
uv sync --frozen
export SCRAPER_AUTH_TOKEN=$(openssl rand -hex 32)
./start.sh
```

The authenticated endpoint is `http://127.0.0.1:8000/mcp`. HTTP startup fails if
the token is absent or blank. The launcher stays in the foreground; use a service
manager for supervision. Local desktop clients can instead use:

```bash
SCRAPER_TRANSPORT=stdio uv run --frozen web-scraper-mcp
```

Stdio does not require a token. Never log or commit bearer tokens or API keys.
Copy `.env.example` to `.env` to configure the service; `.env` is ignored by Git.

An HTTP client configuration:

```json
{
  "mcpServers": {
    "web-scraper": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

## Containers and rendering

Build the reviewed source locally:

```bash
docker build -t web-scraper-mcp:local .
docker run --rm -p 127.0.0.1:8000:8000 \
  -e SCRAPER_AUTH_TOKEN web-scraper-mcp:local
```

This runs static fetching. For sandboxed rendering, `compose.yaml` puts the app
on an internal-only network and routes outbound traffic through the separate
`egress` service. The proxy has no published port and cannot disable its public-IP
policy. The app has a read-only filesystem, temporary storage, and CPU, memory,
and process limits. Chromium runs as a non-root user with its sandbox enabled.

```bash
export SCRAPER_AUTH_TOKEN=$(openssl rand -hex 32)
docker compose up --build
```

Review [the seccomp profile provenance](deploy/README.md) before deploying.
Use Docker Engine 28 or newer for localhost port isolation.
Unprivileged user namespaces must be supported by the host. Rendering fails if
sandbox initialization fails; it never falls back to `--no-sandbox`. Setting
`SCRAPER_EGRESS_PROXY_URL` alone does not create network isolation; use the
internal-network topology or equivalent firewall enforcement.

An internal Docker bridge still permits access to host services bound to its
bridge address. The HTTP broker rejects those destinations. For containment
against a compromised browser process, also restrict host-bound traffic with a
host firewall or use an isolated gateway network and a separate ingress service;
see [Docker gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes).

Browser HTTP resources are fetched by the guarded broker and fulfilled locally;
the browser does not follow upstream redirects directly. WebSockets, service
workers and downloads are blocked. Read-only scraping blocks writes. During an
explicit browser action, writes are allowed only to the current page origin and
are checked again on redirects. Unprompted writes and cross-origin writes are
blocked. Some JavaScript sites need unsupported features and will fail. Anti-bot challenges and CAPTCHAs may also fail.

Compose does not provision Ollama. For local models, add an Ollama service only
to the internal network, named `ollama`, or configure a trusted endpoint reachable
from that network. An external endpoint, including a Tailscale endpoint, needs
an explicitly provisioned trusted route or model relay; the internal bridge
does not provide outbound routing. Native stdio/HTTP deployments can connect
to a reachable `OLLAMA_HOST` directly. Do not give the scraper a second outbound
network. Use
Anthropic with an API key and explicit model/provider settings if desired.

## Models and schema validation

Both model tools default to Ollama with model `llama3.1`. Set
`SCRAPER_EXTRACT_PROVIDER` and `SCRAPER_RESEARCH_PROVIDER` to `anthropic` or
`ollama` explicitly, and select installed/available models with the corresponding
`*_MODEL` setting. `auto` chooses Anthropic for model names starting `claude-`.
Anthropic requires `ANTHROPIC_API_KEY`; Ollama requires a separately running model
server. `OLLAMA_HOST` and `SCRAPER_OLLAMA_HOST` are supported.

Page text is passed as untrusted data. Input is truncated to a UTF-8 byte budget
(default 16,000), with space reserved for the task, schema, framing, and output.
Ollama receives configurable `num_ctx` (32,768) and `num_predict` (2,048).
`SCRAPER_OLLAMA_THINK=false` defaults to reserving generation for the answer; set
`true` to request thinking, or leave the setting empty to use the model default.
Models that cannot disable thinking require the empty setting and a suitable
output budget. Model requests use the total tool deadline, independently of the
shorter page-fetch timeout. See [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking).
Truncated/incomplete model responses are rejected. Ensure your model and hardware
support the chosen context. Prompt framing cannot guarantee immunity to prompt
injection; validate important extracted facts against the original source.

Schemas use JSON Schema 2020-12, limited to 16 KB, 512 nodes, and depth 12.
Remote/root references, `$id`, `pattern`, and `patternProperties` are unsupported.
Output validation is limited to 64 KB, 1,024 nodes, and depth 16. Citation checking
verifies source indices; it does not prove that a cited source supports a claim.

## Configuration and security boundaries

See [.env.example](.env.example) and [Settings](src/web_scraper_mcp/config.py) for
settings and accepted ranges.

| Setting | Default | Purpose |
| --- | --- | --- |
| `SCRAPER_AUTH_TOKEN` | required for HTTP | Bearer authentication; stdio can omit it. |
| `SCRAPER_RESPECT_ROBOTS` | `true` | Recheck robots policy at every redirected destination; failures deny access. |
| `SCRAPER_ALLOW_PRIVATE_NETWORKS` | `false` | Local testing override for direct static fetching only; keep false in deployments. |
| `SCRAPER_MAX_RESPONSE_BYTES` | `5000000` | Cap compressed wire bytes and decoded response bytes while streaming. |
| `SCRAPER_REQUEST_TIMEOUT_S` | `30` | Total fetch deadline, including policy checks and redirects. |
| `SCRAPER_TOOL_TIMEOUT_S` | `180` | Total tool deadline. |
| `SCRAPER_MAX_CONCURRENT_TOOLS` | `8` | Reject excess tool work. |
| `SCRAPER_MAX_CONCURRENT_FETCHES` | `8` | Fetch admission limit. |
| `SCRAPER_MAX_CONCURRENT_PAGES` | `4` | Browser page limit. |
| `SCRAPER_MAX_CONCURRENT_LLM` | `2` | Model request admission limit. |
| `SCRAPER_MAX_CONCURRENT_CRAWLS` | `2` | Background job admission limit. |
| `SCRAPER_MAX_CRAWL_JOBS` | `16` | Stored jobs; expired or oldest completed jobs can be removed. |
| `SCRAPER_CRAWL_TTL_S` | `600` | Retain completed/cancelled jobs for this long. |
| `SCRAPER_MAX_BROWSER_SESSIONS` | `2` | Persistent sessions reserve shared browser page capacity. |
| `SCRAPER_BROWSER_SESSION_TTL_S` | `300` | Idle session lifetime; explicit calls refresh it. |
| `SCRAPER_BROWSER_ENABLED` | `false` | Enable guarded rendering; Compose explicitly enables it. |
| `SCRAPER_EGRESS_PROXY_URL` | unset | Trusted guarded HTTP proxy; required for rendering. |

Direct static connections resolve asynchronously once and connect only to
approved literal public IPs while retaining the original HTTP Host, TLS SNI, and
certificate checks. Mixed public/private DNS answers are denied. Proxy mode
relies on the configured proxy to enforce that connection policy. The bundled
proxy enforces it for both ordinary HTTP and HTTPS CONNECT (port 443 only).
Caller URLs cannot contain embedded credentials or ambiguous authority syntax.

Scrape link output is capped at 1,000 links and 256 KB total; `map` accepts up to
2,000 links with the same byte cap. Crawl defaults are 20 requested pages and
depth 2, clamped to server limits of 100 pages and depth 3. Frontiers are capped
at 1,000 URLs; accumulated results/failures at 5 MB; the job deadline is 180
seconds. Same-domain crawling compares normalized host and effective authority
(default ports omitted), and rejects redirects to another host or non-default
port. Jobs and sessions live in memory, share the server bearer token, and close
on shutdown. Browser sessions have independent cookie contexts; cookies are
restricted to their response host and capped at 100 distinct names/paths.
Snapshots are capped at 64 KB. Browser resource/byte budgets apply to the entire
session, so close and reopen it when a limit is reached. Fingerprint mitigation
is optional (`SCRAPER_BROWSER_STEALTH=true`) and does not guarantee challenge bypass. Rate/robots caches
have entry and TTL bounds. Parsing and blocking search run in
a bounded worker pool; cancelled waiters cannot admit replacements until their
threads finish. DNS admission likewise remains occupied until resolution ends.
The proxy's TLS tunnels have byte and duration bounds; decoded resource caps
are enforced by the HTTP broker. Resource caps reduce denial-of-service exposure
but do not make parsing arbitrary hostile pages risk-free.

Trusted server settings such as Ollama/SearXNG endpoints may point to internal
services. Do not expose the proxy directly or configure an untrusted proxy.
One bearer token grants all ten tools; there is no per-user quota or tenancy
isolation. Keep HTTP behind TLS when accessed beyond localhost.

## Validation and releases

```bash
uv sync --frozen
uv run ruff check src tests benchmarks scripts
uv run ruff format --check src tests benchmarks scripts
uv run mypy src
uv run bandit -r src -ll
uv run pytest -q
uv run python scripts/audit_dependencies.py
```

GitHub checks Python 3.11–3.13, lint, formatting, typing, Bandit, tests, secrets,
and locked dependencies. Stable version tags matching the package version on the default-branch revision
trigger a release. Release builds scan the exact local image before any registry
push. Docker Hub tags are immutable, so releases publish a new version and full
commit tag; they do not overwrite the historical `latest` tag. HIGH/CRITICAL findings, including unfixed OS findings, block
publication. Actions and base images are pinned. GitLab validates source and
images; it does not publish a competing `latest` tag.

The canonical release workflow is GitHub → Docker Hub, configured by
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets. Only a successful
release signs the published digest and attaches an SPDX SBOM with GitHub OIDC.
Existing historical images are not retroactively signed. Verify a released
image using the exact repository and ref that produced it:

```bash
IMAGE='docker.io/YOUR_NAMESPACE/web-scraper-mcp@sha256:YOUR_DIGEST'
IDENTITY='https://github.com/YOUR_OWNER/YOUR_REPO/.github/workflows/docker-publish.yml@refs/heads/main'
cosign verify --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "$IDENTITY" "$IMAGE"
cosign verify-attestation --type spdxjson \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "$IDENTITY" "$IMAGE"
```

For a tagged release, use `refs/tags/TAG` in the identity. Check
[remediation validation](docs/review/2026-10-05-remediation.md) for current blockers;
a successful build alone does not establish release readiness.

## Benchmark

```bash
uv run python benchmarks/run.py --output scorecard.md
```

This measures parser token F1 on the small, bundled offline fixtures. It does
not measure live fetching, challenge bypass, JavaScript rendering, schema
accuracy, or model quality. Optional Crawl4AI comparison runs only when installed
and explicitly requested. Output records the source revision, dirty status,
Python/dependency versions, and fixture hash; [scorecard.md](scorecard.md) reports
actual results rather than extrapolated production accuracy.
