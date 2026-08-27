# Web Scraper MCP

A self-hosted [Model Context Protocol](https://modelcontextprotocol.io) server
that gives an LLM client (Claude Code, Cursor, ChatGPT) the same tool surface as
paid scraping services — **scrape, crawl, map, search, extract, interact,
deep_research** — running entirely on your own hardware.

No paid proxy/CAPTCHA services: anti-bot is self-hosted (headless Chromium +
[playwright-stealth](https://pypi.org/project/playwright-stealth/), robots.txt,
polite rate limiting). Hardened sites may still block; see [Limitations](#limitations).

## Tools

| Tool | What it does |
|------|--------------|
| `scrape` | One URL → clean markdown (boilerplate stripped). Static-first, auto browser fallback for JS pages. |
| `crawl` / `check_crawl_status` | Background BFS crawl job (dedup, depth/page caps); poll for results. |
| `map` | List the links on a page (optionally same-domain) — decide what to crawl. |
| `search` | Web search. Pluggable backend: DuckDuckGo (default), SearXNG, Brave, or Tavily. |
| `extract` | Fetch a page and pull **structured JSON** matching your schema, via an LLM. |
| `browser_navigate` / `browser_act` / `browser_close` | Drive a persistent browser session (click/fill/press) using token-cheap ARIA snapshots. |
| `deep_research` | Search → read top sources → return a cited synthesis report. |

`extract` and `deep_research` require `ANTHROPIC_API_KEY`.

## Quick start

```bash
uv sync                      # install deps (uses the pinned uv.lock)
uv run playwright install chromium
export SCRAPER_AUTH_TOKEN=$(openssl rand -hex 32)
uv run web-scraper-mcp       # HTTP server on http://127.0.0.1:8000/mcp
```

Stdio (local, for a desktop client): `SCRAPER_TRANSPORT=stdio uv run web-scraper-mcp`.

### Docker

The fastest way to get started is by pulling the pre-built image from DockerHub.

```bash
# Pull the latest image
docker pull PROG_UP_USERNAME/web-scraper-mcp:latest

# Run the container (with Anthropic / Claude)
docker run -p 8000:8000 \
  -e SCRAPER_AUTH_TOKEN=your_secure_token_here \
  -e ANTHROPIC_API_KEY=sk-ant-api03-... \
  PROG_UP_USERNAME/web-scraper-mcp:latest

# Or run the container over stdio (useful for local MCP clients)
docker run -i --rm \
  -e SCRAPER_TRANSPORT=stdio \
  -e SCRAPER_AUTH_TOKEN=your_secure_token_here \
  PROG_UP_USERNAME/web-scraper-mcp:latest
```
*(Make sure to replace `PROG_UP_USERNAME` with your actual DockerHub username).*

### Using Local Models (Ollama) & Context Windows

If you prefer to run models locally instead of using Anthropic's API, the server fully supports **Ollama** as an alternative backend for the `extract` and `deep_research` tools.

```bash
docker run -p 8000:8000 \
  -e SCRAPER_AUTH_TOKEN=your_secure_token_here \
  -e SCRAPER_OLLAMA_HOST=http://host.docker.internal:11434 \
  -e SCRAPER_EXTRACT_MODEL=qwen3.5:2b \
  -e SCRAPER_RESEARCH_MODEL=qwen3.5:2b \
  PROG_UP_USERNAME/web-scraper-mcp:latest
```

> [!WARNING]
> **Context Windows are Critical!**
> Web scraping produces a massive amount of Markdown. `extract` can send up to 100,000 characters and `deep_research` can send up to 16,000 characters to the LLM. 
> 
> By default, Claude handles massive contexts natively. However, Ollama's default context window (`num_ctx`) is often configured to just 2,048 tokens. If you pass an enormous Wikipedia page to a local model, it will silently truncate the prompt (dropping your instructions) and return empty strings! 
> 
> **We automatically pass `"num_ctx": 32768` to Ollama** in the API payloads to prevent this truncation. Ensure that your local machine has enough RAM/VRAM to support a 32K context window when using Ollama!

### Register in a client (`mcp.json`)

If running via HTTP:
```json
{
  "mcpServers": {
    "web-scraper": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer your_secure_token_here" }
    }
  }
}
```

If running via stdio (Docker):
```json
{
  "mcpServers": {
    "web-scraper": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "SCRAPER_TRANSPORT=stdio",
        "-e", "SCRAPER_OLLAMA_HOST=http://host.docker.internal:11434",
        "-e", "SCRAPER_EXTRACT_MODEL=qwen3.5:2b",
        "-e", "SCRAPER_RESEARCH_MODEL=qwen3.5:2b",
        "PROG_UP_USERNAME/web-scraper-mcp:latest"
      ]
    }
  }
}
```

## Configuration

All settings are env vars (prefix `SCRAPER_`), or a `.env` file — see
[.env.example](.env.example).

| Var | Default | Notes |
|-----|---------|-------|
| `SCRAPER_AUTH_TOKEN` | _(unset)_ | Bearer token for the HTTP endpoint. **Required** for any networked deploy; unset = unauthenticated (warned). |
| `SCRAPER_HOST` / `SCRAPER_PORT` | `127.0.0.1` / `8000` | Bind address. Docker image sets host `0.0.0.0`. |
| `SCRAPER_MAX_CONCURRENT_PAGES` | `8` | Headless-page concurrency cap (RAM/CPU bound). |
| `SCRAPER_MAX_CRAWL_PAGES` / `_DEPTH` | `100` / `3` | Hard ceilings for crawl jobs. |
| `SCRAPER_PER_DOMAIN_DELAY_S` | `1.0` | Polite per-domain rate limit. |
| `SCRAPER_RESPECT_ROBOTS` | `true` | Honour robots.txt. |
| `SCRAPER_ALLOW_PRIVATE_NETWORKS` | `false` | **Keep false** — disables the SSRF guard if true. |
| `ANTHROPIC_API_KEY` | _(unset)_ | Enables `extract` / `deep_research`. |
| `SCRAPER_SEARXNG_URL`, `BRAVE_API_KEY`, `TAVILY_API_KEY` | _(unset)_ | Optional search backends (first set wins, else DuckDuckGo). |

## Security

- **SSRF guard** — every fetched URL (and each redirect hop) is DNS-resolved and
  rejected if it points at a private / loopback / link-local / cloud-metadata
  address. The browser also aborts subresource requests to private IPs.
- **Auth** — bearer token on the HTTP transport; bind localhost by default.
- **Resource caps** — response-size, timeout, page-concurrency, crawl page/depth
  limits to protect the host.
- **robots.txt + rate limiting** on by default.
- **Container** — runs as a non-root user; secrets via env only.

## Supply chain — verifying the image

CI signs the image keylessly with [cosign](https://github.com/sigstore/cosign)
(Sigstore) using GitLab's OIDC identity, and attaches an SPDX SBOM attestation.
Verify before running:

```bash
cosign verify \
  --certificate-oidc-issuer https://gitlab.cri.epita.fr \
  --certificate-identity-regexp 'https://gitlab.cri.epita.fr/enzo.juhel/web-scraper//.*' \
  registry.gitlab.cri.epita.fr/enzo.juhel/web-scraper@sha256:...
```

## Benchmark

`benchmarks/run.py` scores our `scrape`/`extract` against public datasets and
the Crawl4AI baseline, emitting a scorecard (per page-type F1/accuracy + a
Limitations section). Run locally or via the manual CI `benchmark` job:

```bash
uv run python benchmarks/run.py --output scorecard.md
```

## Limitations

- No paid proxies/CAPTCHA: heavily-defended sites (LinkedIn, Amazon, Cloudflare
  challenges) will sometimes block us. The benchmark scorecard quantifies where.
- Main-content extraction is strong on articles, weaker on forums / product /
  listing pages (a known property of all extractors).
- In-memory crawl/session state — single-process, single-user by design.

## Development

```bash
uv run pre-commit install        # local lint/secret hooks
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -q
```
