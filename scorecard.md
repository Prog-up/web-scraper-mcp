# Scraper Benchmark Scorecard

Token-level F1 of main-content extraction vs. gold. Higher is better.

| page type | n | ours | raw-text |
|---|---|---|---|
| article | 1 | 1.000 | 0.833 |
| forum | 1 | 0.949 | 0.738 |
| listing | 1 | 0.880 | 0.500 |
| product | 1 | 0.945 | 0.703 |
| **overall** | 4 | 0.944 | 0.694 |

## Limitations (our weakest page types)

- **listing**: F1 0.880 — extraction here is least reliable.
- **product**: F1 0.945 — extraction here is least reliable.

_Expected: strong on articles, weaker on listing/forum/product pages — a known property of all main-content extractors. No paid proxies/CAPTCHA, so hardened live sites may block entirely._
