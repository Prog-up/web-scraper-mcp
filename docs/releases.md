# Releases and validation

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
publication, except for the explicitly approved, exact package/CVE inventory for
[release 1.1.0](releases/1.1.0.md), expiring 13 October 2026. Fixable and
additional findings remain blocked; full reports are retained. Actions and base
images are pinned. GitLab validates source and images; it does not publish a competing `latest` tag.

The canonical release workflow is GitHub → Docker Hub, configured by
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets. Only a successful
release signs the published digest and attaches an SPDX SBOM with GitHub OIDC.
Existing historical images are not retroactively signed. Verify a released
image using the exact repository and ref that produced it:

```bash
IMAGE='docker.io/YOUR_NAMESPACE/web-scraper-mcp@sha256:YOUR_DIGEST'
IDENTITY='https://github.com/YOUR_OWNER/YOUR_REPO/.github/workflows/docker-publish.yml@refs/tags/1.1.0'
cosign verify --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "$IDENTITY" "$IMAGE"
cosign verify-attestation --type spdxjson \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "$IDENTITY" "$IMAGE"
```

For a tagged release, use `refs/tags/TAG` in the identity. A successful build alone
does not establish release readiness: source checks, sandbox tests, the image
vulnerability gate, and signature/SBOM verification must all succeed.

Create a new version tag only after updating `pyproject.toml`, refreshing
`uv.lock`, recording changes in `CHANGELOG.md`, and merging to the default branch.
The 1.1.0 exception does not apply to a different release.
