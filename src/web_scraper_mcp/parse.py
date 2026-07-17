"""HTML → markdown and link extraction. Shared by scrape / crawl / map."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import trafilatura
from selectolax.parser import HTMLParser


def _fallback_markdown(html: str) -> str:
    """Fallback layout parser when main-content extractor fails."""

    parser = HTMLParser(html)
    for tag in ("script", "style", "head", "iframe", "svg"):
        for node in parser.css(tag):
            node.decompose()
    body = parser.body
    return body.text(separator="\n", strip=True) if body else ""


def to_markdown(html: str, url: str) -> str:
    """Clean main-content markdown (nav/ads/boilerplate stripped)."""
    md = trafilatura.extract(html, url=url, output_format="markdown", include_links=True) or ""
    if len(md.strip()) < 500:
        fallback = _fallback_markdown(html)
        if len(fallback) > len(md) * 2:
            return fallback
    return md


def title_of(html: str) -> str | None:
    node = HTMLParser(html).css_first("title")
    return node.text(strip=True) if node else None


def extract_links(html: str, base_url: str, *, same_domain: bool = False) -> list[str]:
    """Absolute http(s) links on the page, de-duplicated, order preserved."""
    base_host = urlparse(base_url).netloc
    seen: set[str] = set()
    out: list[str] = []
    for a in HTMLParser(html).css("a[href]"):
        href = a.attributes.get("href")
        if not href:
            continue
        absolute = urljoin(base_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if same_domain and parsed.netloc != base_host:
            continue
        clean = absolute.split("#", 1)[0]
        if clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out
