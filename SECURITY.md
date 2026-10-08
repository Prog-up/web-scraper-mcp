# Security policy

## Reporting vulnerabilities

Use **Report a vulnerability** in the repository's
[Security tab](https://github.com/Prog-up/web-scraper-mcp/security) when available.
If private reporting is unavailable, open an issue requesting a private reporting
channel without including credentials, exploit details or sensitive data.

Include the affected version or commit, deployment mode, reproduction steps and
impact in the private report. Redact tokens, endpoint credentials and private
page content. There is no guaranteed response time; support is community-based.
Security fixes target the current default branch and latest release; older
releases may require an upgrade.

## Deployment boundaries

- HTTP requires a bearer token; stdio relies on the local client's process access.
  All tools share one token. There is no tenant isolation or per-user quota.
- Use TLS and trusted ingress boundaries for access beyond localhost. Keep
  `.env`, provider keys and bearer tokens outside Git and distributable artifacts.
- Caller-supplied URLs are checked against public-destination policy, including
  redirects. Trusted operator settings for model/search services may address
  internal endpoints; those settings must not be controlled by untrusted users.
- Rendering requires sandboxed Chromium and guarded, isolated egress. Never
  disable the sandbox or use a privileged container as a compatibility fix.
  Review [deployment](docs/deployment.md) and [seccomp provenance](deploy/README.md).
- Explicit browser actions may write to the current origin. Downloads,
  WebSockets, service workers, background writes and cross-origin writes are
  blocked. Treat page content as untrusted input.
- Resource limits and prompt framing reduce exposure; they do not establish
  immunity to malicious pages, denial of service or prompt injection. Validate
  important model-derived facts against original sources.

## Dependencies and releases

CI scans source, secrets and locked dependencies. The release pipeline tests the
exact container, scans HIGH/CRITICAL findings including unfixed vulnerabilities,
then signs the published image digest and attaches an SPDX SBOM.

Release **1.1.0 contains a time-limited exception for known unfixed Debian
vulnerabilities**, including one CRITICAL finding. See the
[release disclosure](docs/releases/1.1.0.md) and
[exact inventory](deploy/release-exceptions/1.1.0.json). The exception expires on
13 October 2026 and does not apply to later versions. Cleanup and successful
functional tests do not establish that an image is vulnerability-free.

See [release verification](docs/releases.md) for the signature and SBOM commands.
