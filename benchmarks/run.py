"""Benchmark our scraper's main-content extraction and emit a scorecard.

Scores each comparator with token-level F1 against gold, per page type, so weak
spots are explicit. Comparators:
  - ours      : trafilatura main-content extraction (what the server uses)
  - raw-text  : naive full-body text (no boilerplate removal) — baseline
  - crawl4ai  : optional open-source baseline (only if installed)

Usage:
  uv run python benchmarks/run.py [--output scorecard.md] [--comparator crawl4ai]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from selectolax.parser import HTMLParser

# Make the package (src/) and the sibling datasets module importable when run
# as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datasets import CASES, Case, token_f1  # noqa: E402

from web_scraper_mcp.parse import to_markdown  # noqa: E402


def _ours(case: Case) -> str:
    return to_markdown(case.html, f"https://example.test/{case.id}")


def _raw_text(case: Case) -> str:
    body = HTMLParser(case.html).body
    return body.text(separator=" ", strip=True) if body else ""


def _crawl4ai_available() -> bool:
    try:
        import crawl4ai  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _crawl4ai(case: Case) -> str:
    # Optional baseline. crawl4ai is browser/URL oriented; we use its HTML->md
    # converter directly when present. Skipped entirely if not installed.
    from crawl4ai.html2text import HTML2Text  # type: ignore

    h = HTML2Text()
    h.ignore_links = True
    return h.handle(case.html)


def run(comparators: dict[str, object]) -> dict:
    per_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    rows = []
    for case in CASES:
        row = {"id": case.id, "page_type": case.page_type, "scores": {}}
        for name, fn in comparators.items():
            try:
                pred = fn(case)  # type: ignore[operator]
                score = token_f1(case.gold, pred)
            except Exception as exc:  # noqa: BLE001
                score = 0.0
                row["scores"][name + "_error"] = str(exc)
            row["scores"][name] = round(score, 3)
            per_type[case.page_type][name].append(score)
        rows.append(row)

    summary = {
        ptype: {name: round(statistics.mean(scores), 3) for name, scores in by_name.items()}
        for ptype, by_name in per_type.items()
    }
    overall = {
        name: round(
            statistics.mean([row["scores"][name] for row in rows if name in row["scores"]]), 3
        )
        for name in comparators
    }
    return {"rows": rows, "by_page_type": summary, "overall": overall}


def _scorecard_md(result: dict, comparators: list[str]) -> str:
    lines = ["# Scraper Benchmark Scorecard", ""]
    lines.append("Token-level F1 of main-content extraction vs. gold. Higher is better.")
    lines.append("")
    header = "| page type | n | " + " | ".join(comparators) + " |"
    sep = "|---|---|" + "---|" * len(comparators)
    lines += [header, sep]
    counts: dict[str, int] = defaultdict(int)
    for row in result["rows"]:
        counts[row["page_type"]] += 1
    for ptype, scores in sorted(result["by_page_type"].items()):
        cells = " | ".join(f"{scores.get(c, 0):.3f}" for c in comparators)
        lines.append(f"| {ptype} | {counts[ptype]} | {cells} |")
    overall_cells = " | ".join(f"{result['overall'].get(c, 0):.3f}" for c in comparators)
    lines.append(f"| **overall** | {len(result['rows'])} | {overall_cells} |")

    # Limitations: our weakest page types.
    ours_by_type = {p: s.get("ours", 0.0) for p, s in result["by_page_type"].items()}
    weakest = sorted(ours_by_type.items(), key=lambda kv: kv[1])[:2]
    lines += ["", "## Limitations (our weakest page types)", ""]
    for ptype, score in weakest:
        lines.append(f"- **{ptype}**: F1 {score:.3f} — extraction here is least reliable.")
    lines += [
        "",
        "_Expected: strong on articles, weaker on listing/forum/product pages — a "
        "known property of all main-content extractors. No paid proxies/CAPTCHA, so "
        "hardened live sites may block entirely._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="scorecard.md", help="Markdown scorecard path.")
    parser.add_argument(
        "--comparator", action="append", default=[], help="Extra comparator (e.g. crawl4ai)."
    )
    args = parser.parse_args()

    comparators: dict[str, object] = {"ours": _ours, "raw-text": _raw_text}
    if "crawl4ai" in args.comparator:
        if _crawl4ai_available():
            comparators["crawl4ai"] = _crawl4ai
        else:
            print(
                "crawl4ai not installed — skipping that comparator "
                "(install with: uv add --optional benchmark crawl4ai)"
            )

    result = run(comparators)
    md = _scorecard_md(result, list(comparators))
    Path(args.output).write_text(md)
    Path("benchmarks/scorecard.json").write_text(json.dumps(result, indent=2))
    print(md)


if __name__ == "__main__":
    main()
