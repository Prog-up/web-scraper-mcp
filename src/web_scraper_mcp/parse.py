"""Shared HTML → markdown, title and link extraction."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import trafilatura
from selectolax.parser import HTMLParser

from .security import parse_url


def canonical_url(url: str) -> str:
    """Normalize authority/default ports and discard fragments for traversal dedup."""
    host, port = parse_url(url)
    parsed = urlsplit(url)
    host = host.lower().rstrip(".")
    authority = f"[{host}]" if ":" in host else host
    if port != (443 if parsed.scheme == "https" else 80):
        authority += f":{port}"
    return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))


def same_host(left: str, right: str) -> bool:
    """Compare normalized authority, treating each scheme's default port as implicit."""
    return urlsplit(canonical_url(left)).netloc == urlsplit(canonical_url(right)).netloc


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


def extract_links(
    html: str, base_url: str, *, same_domain: bool = False, limit: int = 1000
) -> list[str]:
    """Absolute links, de-duplicated; at most 2,000 links and 256 KB total."""
    seen: set[str] = set()
    out: list[str] = []
    total_bytes = 0
    for a in HTMLParser(html).css("a[href]"):
        href = a.attributes.get("href")
        if not href:
            continue
        absolute = urljoin(base_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        try:
            clean = canonical_url(absolute)
            if same_domain and not same_host(clean, base_url):
                continue
        except ValueError:
            continue
        size = len(clean.encode())
        if size > 8192:
            continue
        if clean not in seen:
            if len(out) >= min(limit, 2000) or total_bytes + size > 256_000:
                break
            seen.add(clean)
            out.append(clean)
            total_bytes += size
    return out
