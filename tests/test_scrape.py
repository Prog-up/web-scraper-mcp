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


def test_short_catalog_keeps_all_prices_without_navigation_or_ads():
    html = """<html><body><header><nav>Home Login About</nav></header>
    <aside>BUY NOW! Sponsored giveaway</aside>
    <ul><li>Blue shoes $60</li><li>Red boots $95</li><li>Green sandals $30</li></ul>
    <footer>Privacy Cookies Terms</footer></body></html>"""
    markdown = to_markdown(html, BASE)
    for expected in ("Blue shoes", "$60", "Red boots", "$95", "Green sandals", "$30"):
        assert expected in markdown
    for boilerplate in ("Login", "Sponsored", "giveaway", "Cookies", "Privacy"):
        assert boilerplate not in markdown


def test_short_article_preserves_its_own_header_and_footer():
    html = """<html><body><header>Site banner</header>
    <article><header><h1>Experiment result</h1></header>
    <p>The measured temperature was 23 degrees Celsius.</p>
    <footer>Author: Alice, laboratory notes</footer></article>
    <footer>Site privacy policy</footer></body></html>"""
    markdown = to_markdown(html, BASE)
    assert "Experiment result" in markdown and "23 degrees" in markdown
    assert "Site banner" not in markdown and "Site privacy policy" not in markdown
