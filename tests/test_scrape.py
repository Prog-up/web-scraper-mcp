"""Parsing helpers — pure functions, no network."""

from web_scraper_mcp.parse import extract_links, title_of, to_markdown

FIXTURE = """
<html><head><title>Hello World</title></head>
<body>
  <nav><a href="/home">home</a></nav>
  <article>
    <h1>Main Heading</h1>
    <p>This is the real article body with enough text to be extracted cleanly
    by the main-content extractor and turned into markdown output.</p>
    <a href="https://other.example/page">external</a>
    <a href="/about">about</a>
  </article>
</body></html>
"""

BASE = "https://site.example/post"


def test_title():
    assert title_of(FIXTURE) == "Hello World"


def test_to_markdown_keeps_body_drops_nothing_critical():
    md = to_markdown(FIXTURE, BASE)
    assert "Main Heading" in md
    assert "real article body" in md


def test_extract_links_absolute_and_deduped():
    links = extract_links(FIXTURE, BASE)
    assert "https://site.example/home" in links
    assert "https://site.example/about" in links
    assert "https://other.example/page" in links
    assert len(links) == len(set(links))


def test_extract_links_same_domain_filter():
    links = extract_links(FIXTURE, BASE, same_domain=True)
    assert "https://other.example/page" not in links
    assert "https://site.example/about" in links
