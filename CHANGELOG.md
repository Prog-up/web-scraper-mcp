# Changelog

## Unreleased

## [1.1.1](https://github.com/Prog-up/web-scraper-mcp/releases/tag/1.1.1) — 2026-10-08

- Retain the same 59 HIGH and one CRITICAL unfixed Debian findings under an
  explicitly approved 1.1.1 inventory, expiring 13 October 2026 at 23:59:59 UTC.
  Additional or fixable findings remain blocked; this is not a clean image scan.
- Correct the internal package version to match release metadata.
- Fetch crawl pages in bounded parallel batches while preserving discovery order,
  cancellation cleanup, result limits and shared worker capacity.
- Improve short-page extraction by removing navigation and page chrome while
  preserving article headers and product listings.
- Request Ollama structured extraction through JSON Schema output mode and keep
  local schema/input-budget validation.
- Give research models concrete citation numbers and reject literal placeholders.
- Add regression coverage for crawl concurrency, cancellation, parser completeness
  and structured model output, plus a reproducible MCP tool benchmark.
- Prepare public setup, deployment, configuration, contribution and security docs.
  Archive local diagnostics and dated review reports outside tracked release
  files, restrict build inputs, and retain historical release security evidence.
- Add package license/repository metadata, identify the public repository in the
  default HTTP user agent and expose crawl concurrency in Compose configuration.

## [1.1.0](https://github.com/Prog-up/web-scraper-mcp/releases/tag/1.1.0) — 2026-10-06

- Provide ten tools for bounded fetching, crawling, mapping, browser interaction,
  search, extraction and research through stdio and authenticated HTTP.
- Enforce public-destination checks, guarded browser egress, sandboxing, resource
  limits, schema validation and session/job cleanup.
- Refresh Python/Debian dependencies and publish through a validated, signed
  Docker Hub release workflow with an SPDX SBOM.
- Disclose the [approved, expiring security exception](docs/releases/1.1.0.md).
