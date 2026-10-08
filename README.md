# Web Scraper MCP

A self-hosted [Model Context Protocol](https://modelcontextprotocol.io/) server
for reading public web pages, bounded crawling, search, model-backed extraction
and browser interaction. Supports Python 3.11–3.13 and stdio or authenticated HTTP.

Run it with your own models and infrastructure. Fetching is static by default;
browser rendering is optional and uses sandboxed Chromium with guarded egress.

## Tools

| Tool | Behavior |
| --- | --- |
| `scrape` | Fetch a public URL and return its title, Markdown and optional capped links or HTML. |
| `crawl` | Start a background crawl with page/depth limits and an optional same-host policy. |
| `check_crawl_status` | Read progress/results or cancel a job while retaining completed pages. |
| `map` | Return canonical, deduplicated links; defaults to the source host. |
| `browser_navigate` | Create or reuse a browser session and return an ARIA snapshot. |
| `browser_act` | Click, fill, press, select or wait using a selector. Explicit actions may submit same-origin forms. |
| `browser_close` | Close a session and release its page capacity. |
| `search` | Use Tavily, Brave, SearXNG or DuckDuckGo, in that priority order. |
| `extract` | Ask Ollama or Anthropic for text or data matching a locally validated JSON Schema. |
| `deep_research` | Search, read bounded sources and synthesize a report with checked citation indices and source failures. |

## Quick start

Install Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/), then:

```sh
git clone https://github.com/Prog-up/web-scraper-mcp.git
cd web-scraper-mcp
uv sync --frozen
cp .env.example .env
```

For a local MCP client using stdio:

```sh
SCRAPER_TRANSPORT=stdio uv run --frozen web-scraper-mcp
```

Stdio does not require a token. Clients with an `mcpServers` configuration can use:

```json
{
  "mcpServers": {
    "web-scraper": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/web-scraper-mcp", "run", "--frozen", "web-scraper-mcp"],
      "env": {"SCRAPER_TRANSPORT": "stdio"}
    }
  }
}
```

For HTTP:

```sh
export SCRAPER_AUTH_TOKEN=$(openssl rand -hex 32)
./start.sh
```

Connect to `http://127.0.0.1:8000/mcp` with
`Authorization: Bearer YOUR_TOKEN`. Keep the token in your client's secret
configuration. HTTP startup rejects missing or blank tokens. The launcher stays
in the foreground; use a service manager for supervision.

Scraping and browser tools do not require an LLM. For `extract` and
`deep_research`, configure an installed Ollama model and reachable endpoint in
`.env`, or select Anthropic and supply its API key. Search defaults to DuckDuckGo;
other providers are optional. See [configuration](docs/configuration.md) and
[the environment template](.env.example).

## Docker and browser tools

For sandboxed rendering and browser sessions:

```sh
export SCRAPER_AUTH_TOKEN=$(openssl rand -hex 32)
docker compose up --build
```

Compose runs the app on an internal network with a separate guarded egress
proxy, a read-only filesystem, resource limits and Chromium's sandbox enabled.
Use Docker Engine 28 or newer and a host that supports unprivileged user
namespaces. Sandbox startup failures stop rendering; there is no automatic
fallback that disables the sandbox.

Compose does not start Ollama. Its model endpoint must be reachable from the
isolated app network; an external endpoint needs a trusted route or relay.
See [deployment](docs/deployment.md) for static-only containers, networking,
model connectivity and browser restrictions, and [seccomp provenance](deploy/README.md).

## Scope and limitations

- Intended for public HTTP(S) pages. Private destinations are denied by default.
  Error status pages and unsupported content types are rejected.
- Protected websites, CAPTCHAs and some JavaScript applications may fail.
  There is no managed proxy pool or guaranteed challenge bypass.
- Browser sessions block downloads, WebSockets, service workers and background
  writes. Explicit actions allow writes only to the current page origin.
- Crawl jobs and browser sessions live in memory. They expire and are lost on
  restart; this is not a durable distributed job system.
- One HTTP bearer token grants all tools. There are no per-user quotas or tenant
  isolation; use TLS and trusted access boundaries beyond localhost.
- JSON Schema validation checks output structure. Citation validation checks
  source indices, not whether a source supports every claim. Review important
  extracted facts against the original sources.
- Self-hosting still requires maintenance and compute. Configured search/model
  providers receive their requests; provider fees and policies apply.

## Development and support

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and checks,
[benchmarks](benchmarks/README.md) for reproducible measurements, and
[SECURITY.md](SECURITY.md) for vulnerability reporting and security boundaries.

CI checks Python 3.11–3.13, lint, formatting, typing, tests, secrets and locked
dependencies. Container releases also test the exact sandboxed browser artifact,
scan vulnerabilities, and sign the published digest with an SPDX SBOM.
See [release procedures](docs/releases.md), [release history](CHANGELOG.md) and
the known security exceptions for [1.1.0](docs/releases/1.1.0.md) and
[1.1.1](docs/releases/1.1.1.md).

Report bugs through [GitHub issues](https://github.com/Prog-up/web-scraper-mcp/issues).
Support is community-based, with no service-level agreement.

## License

See [LICENSE](LICENSE) for the existing GNU GPL version 3 terms.
