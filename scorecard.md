# Scraper Benchmark Scorecard

Token-level F1 of main-content extraction vs. gold. Higher is better.

Generated: 2026-10-05T16:33:39.823136+00:00. Scope: bundled offline parser fixtures only.
Source: `87373be62cdf1dd92d1670fa023b3cd608888fd8`; working tree dirty: True.
Python: 3.13.14; dependencies: `{'trafilatura': '2.1.0', 'selectolax': '0.4.10'}`.
Fixture SHA-256: `32db01a0fdcc03ecd1c4963d69563101fdb159f379d832bb92532e89f432fac5`.
This benchmark does not evaluate network fetching, rendering, models, or schema accuracy.

| page type | n | ours | raw-text |
|---|---|---|---|
| article | 1 | 1.000 | 0.833 |
| forum | 1 | 0.949 | 0.738 |
| listing | 1 | 0.500 | 0.500 |
| product | 1 | 0.945 | 0.703 |
| **overall** | 4 | 0.849 | 0.694 |

## Limitations (our weakest page types)

- **listing**: F1 0.500 — extraction here is least reliable.
- **product**: F1 0.945 — extraction here is least reliable.

_Expected: strong on articles, weaker on listing/forum/product pages — a known property of all main-content extractors. No paid proxies/CAPTCHA, so hardened live sites may block entirely._
