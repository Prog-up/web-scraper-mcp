# Deployment

Build and run static fetching:

```sh
docker build -t web-scraper-mcp:local .
docker run --rm -p 127.0.0.1:8000:8000 -e SCRAPER_AUTH_TOKEN web-scraper-mcp:local
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

Review [the seccomp profile provenance](../deploy/README.md) before deploying.
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
