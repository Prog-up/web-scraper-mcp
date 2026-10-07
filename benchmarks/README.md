# Benchmarks

Run from the repository root with `uv sync --frozen` installed.

## Parser fixtures

```sh
uv run python benchmarks/run.py --output scorecard.md
```

This writes a Markdown scorecard and `benchmarks/scorecard.json`, both ignored by
Git. It compares token-level F1 against four bundled HTML/gold fixtures: article,
forum, product and listing. Results include the source revision, dirty status,
Python/dependency versions and fixture hash. Optional Crawl4AI comparison needs
an explicit `--comparator crawl4ai` and a separately installed dependency.

These small fixtures are regression diagnostics. They do not establish real-web
accuracy, protected-site success, browser compatibility or model answer quality.

## MCP tool diagnostics

```sh
uv run python benchmarks/tools.py --mode fixture --samples 5 --output /tmp/tools.json
```

Fixture mode calls the real in-process MCP server, parser and validation with
mocked search/model responses and 50 ms HTTP page delays. It repeats scrape and
crawl cases; other cases run once. To compare serial and parallel crawling, run
the commands sequentially:

```sh
SCRAPER_CRAWL_CONCURRENCY=1 uv run python benchmarks/tools.py --mode fixture --samples 5 --output /tmp/serial.json
SCRAPER_CRAWL_CONCURRENCY=3 uv run python benchmarks/tools.py --mode fixture --samples 5 --output /tmp/parallel.json
```

Live mode reads public Python/Playwright documentation, searches the web and
calls the configured Ollama endpoint. It refuses configured paid provider API
keys. Configure an installed model and reachable endpoint before running:

```sh
uv run python benchmarks/tools.py --mode live --samples 2 --output /tmp/live.json
```

Inspect per-case failures and sample counts. A failed case gives a nonzero exit
status. Output includes timing, output sizes, source hash, model names and relevant
resource settings; it does not include credentials or the private model endpoint.
Live runs depend on upstream load, network and cache state. Fixture mode does not
measure DNS, TLS or inference. Process peak RSS includes the benchmark harness.

Browser tools and isolation are exercised separately by
[`browser_features.py`](../scripts/browser_features.py) and
[`browser_regression.py`](../scripts/browser_regression.py) using the hardened
container settings in the [release workflow](../.github/workflows/docker-publish.yml).
