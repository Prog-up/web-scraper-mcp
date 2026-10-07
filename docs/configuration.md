# Configuration

See [the environment template](../.env.example) for all settings and
[deployment notes](deployment.md) for container networking and rendering.

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
Ollama extraction sends the schema through its structured-output `format` field
and validates the returned JSON locally; Anthropic uses forced tool output.
Remote/root references, `$id`, `pattern`, and `patternProperties` are unsupported.
Output validation is limited to 64 KB, 1,024 nodes, and depth 16. Citation checking
rejects missing/out-of-range indices and literal `[n]` placeholders; it does not
prove that a cited source supports a claim.

## Configuration and security boundaries

See [.env.example](../.env.example) and [Settings](../src/web_scraper_mcp/config.py) for
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
| `SCRAPER_CRAWL_CONCURRENCY` | `3` | Fetch workers per crawl (1–8), bounded by the server fetch limit. |
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
seconds. Crawls fetch bounded batches in discovery order, share worker capacity
across jobs, and retain completed batches when cancelled. Foreground tools still
use the server's admission limits. Same-domain crawling compares normalized host
and effective authority
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
