"""Benchmark cases + scoring metric.

Cases are inlined (HTML + gold main-content text) so the benchmark is
deterministic and runs offline / in CI. They span page types on purpose:
extractors converge on articles but diverge on listing/forum/product pages —
the scorecard is meant to expose that.

For a larger run, point `--live` at real URLs or wire in the public datasets
(Scrapinghub article-extraction-benchmark, WCXB, ScrapeGraphAI-100k); the metric
below is the same token-level F1 those benchmarks use for main-content quality.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_NAV = """
<header><nav><a href="/">Home</a><a href="/about">About</a>
<a href="/login">Login</a></nav></header>
<aside class="ads"><div>BUY NOW! Limited offer, click here to win a prize.</div></aside>
<footer>© 2026 Example Inc. All rights reserved. Privacy. Terms. Cookies.</footer>
"""


@dataclass
class Case:
    id: str
    page_type: str
    html: str
    gold: str  # expected main-content text


CASES: list[Case] = [
    Case(
        id="article-1",
        page_type="article",
        html=f"""<html><head><title>Photosynthesis</title></head><body>{_NAV}
        <article><h1>How Photosynthesis Works</h1>
        <p>Photosynthesis is the process by which green plants convert sunlight
        into chemical energy. Chlorophyll in the leaves absorbs light, which
        drives the conversion of carbon dioxide and water into glucose and
        oxygen.</p>
        <p>The reaction takes place in the chloroplasts and is fundamental to
        life on Earth, supplying both food and atmospheric oxygen.</p>
        </article></body></html>""",
        gold=(
            "How Photosynthesis Works Photosynthesis is the process by which green "
            "plants convert sunlight into chemical energy. Chlorophyll in the leaves "
            "absorbs light, which drives the conversion of carbon dioxide and water "
            "into glucose and oxygen. The reaction takes place in the chloroplasts "
            "and is fundamental to life on Earth, supplying both food and atmospheric "
            "oxygen."
        ),
    ),
    Case(
        id="forum-1",
        page_type="forum",
        html=f"""<html><head><title>Thread</title></head><body>{_NAV}
        <div class="thread">
          <div class="post"><span class="user">alice</span>
            <p>Has anyone solved the timeout error when scraping JS pages?</p></div>
          <div class="post"><span class="user">bob</span>
            <p>Yes, increase the navigation timeout and wait for domcontentloaded.</p></div>
          <div class="post"><span class="user">carol</span>
            <p>Stealth mode also helped me avoid the bot challenge.</p></div>
        </div></body></html>""",
        gold=(
            "alice Has anyone solved the timeout error when scraping JS pages? "
            "bob Yes, increase the navigation timeout and wait for domcontentloaded. "
            "carol Stealth mode also helped me avoid the bot challenge."
        ),
    ),
    Case(
        id="product-1",
        page_type="product",
        html=f"""<html><head><title>Widget</title></head><body>{_NAV}
        <div class="product">
          <h1>Acme Widget Pro</h1>
          <span class="price">$49.99</span>
          <p class="desc">The Acme Widget Pro is a durable stainless-steel widget
          with a lifetime warranty and free shipping.</p>
          <ul><li>Weight: 200g</li><li>Color: silver</li></ul>
        </div></body></html>""",
        gold=(
            "Acme Widget Pro $49.99 The Acme Widget Pro is a durable stainless-steel "
            "widget with a lifetime warranty and free shipping. Weight: 200g Color: silver"
        ),
    ),
    Case(
        id="listing-1",
        page_type="listing",
        html=f"""<html><head><title>Results</title></head><body>{_NAV}
        <ul class="results">
          <li><a href="/p/1">Blue Running Shoes</a> <span>$60</span></li>
          <li><a href="/p/2">Red Hiking Boots</a> <span>$95</span></li>
          <li><a href="/p/3">Green Sandals</a> <span>$30</span></li>
        </ul></body></html>""",
        gold=("Blue Running Shoes $60 Red Hiking Boots $95 Green Sandals $30"),
    ),
]


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def token_f1(gold: str, pred: str) -> float:
    """Word-level F1 between gold and predicted text (multiset overlap)."""
    g, p = Counter(_tokens(gold)), Counter(_tokens(pred))
    overlap = sum((g & p).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(p.values())
    recall = overlap / sum(g.values())
    return 2 * precision * recall / (precision + recall)
