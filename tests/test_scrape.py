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


def test_link_output_is_bounded_even_with_long_base_url():
    html = "<html><body>" + "".join(f'<a href="x{i}">link</a>' for i in range(2000))
    html += "</body></html>"
    short = extract_links(html, BASE)
    assert len(short) == 1000
    long = extract_links(html, "https://site.example/" + "a" * 7900 + "/page")
    assert len(long) < 1000
    assert sum(len(url.encode()) for url in long) <= 256_000
