# Contributing

Use Python 3.11–3.13 and uv. Fork the repository, create a branch and install the
locked development environment:

```sh
uv sync --frozen
uv run pre-commit install
```

Run the source checks before opening a pull request:

```sh
uv run ruff check src tests benchmarks scripts
uv run ruff format --check src tests benchmarks scripts
uv run mypy src
uv run bandit -r src -ll
uv run pytest -q
```

The test suite uses controlled upstreams; localhost sockets and subprocesses
must be available for transport tests. It does not require paid API keys or an
Ollama server. Run `uv run python scripts/audit_dependencies.py` with network
access to check locked packages against OSV. For dependency changes, refresh and
commit `uv.lock`; avoid unrelated dependency upgrades.

Build distributable artifacts with `uv build`. Container or browser changes also
need the sandbox regressions in the [release workflow](.github/workflows/docker-publish.yml).
See [deployment](docs/deployment.md) and [benchmarks](benchmarks/README.md).

Keep changes focused. Explain the problem, resulting behavior and validation in
the pull request. Add meaningful regression coverage for behavior changes.
Do not weaken authentication, destination checks, sandboxing or resource limits
to make a test pass. Security policy changes need explicit review.

Never commit `.env`, tokens, private endpoints, scraped private content or local
diagnostic files. Use `.local/` for personal scratch work; it is excluded from
Git, Docker contexts and source distributions. Remove credentials and sensitive
content from bug reports. Report vulnerabilities through [SECURITY.md](SECURITY.md).

The project uses the existing [GPL version 3 license](LICENSE). Contributions
must be compatible with its terms. Support and review are community-based.
