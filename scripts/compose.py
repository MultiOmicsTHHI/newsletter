#!/usr/bin/env python3
"""Compose the newsletter HTML from recent + throwback JSON files.

Usage: python compose.py recent.json throwback.json > issue.html
"""
from __future__ import annotations

import datetime as dt
import html
import json
import sys
from pathlib import Path


def fmt_paper(p: dict, idx: int) -> str:
    title = html.escape(p.get("title", ""))
    authors = html.escape(p.get("authors", "") or "Authors unavailable")
    venue = html.escape(p.get("venue", "Preprint"))
    date = p.get("date", "")
    doi = p.get("doi", "")
    url = p.get("url") or (f"https://doi.org/{doi}" if doi else "#")
    why_raw = p.get("why_it_matters") or "Summary pending."
    why = html.escape(why_raw)
    return (
        f'<div class="paper">'
        f'  <div class="num">{idx}.</div>'
        f'  <div class="body">'
        f'    <div class="title"><a href="{url}">{title}</a></div>'
        f'    <div class="meta">{authors} · {venue} · {date}</div>'
        f'    <div class="why">▸ {why}</div>'
        f'    <div class="doi">doi:{doi}</div>'
        f'  </div>'
        f'</div>'
    )


def fmt_throwback(t: dict | None) -> str:
    if not t:
        return "<p><em>No throwback paper found this week.</em></p>"
    title = html.escape(t.get("title", ""))
    authors = html.escape(t.get("authors", "") or "Authors unavailable")
    venue = html.escape(t.get("venue", "Unknown"))
    year = t.get("year", "")
    cites = t.get("cited_by_count", 0)
    doi = t.get("doi", "")
    url = t.get("url") or (f"https://doi.org/{doi}" if doi else "#")
    why_raw = t.get("why_it_matters") or "Seminal context pending."
    why = html.escape(why_raw)
    return (
        f'<div class="throwback">'
        f'  <div class="title"><a href="{url}">{title}</a></div>'
        f'  <div class="meta">{authors} · {venue} · {year}</div>'
        f'  <div class="why">▸ {why}</div>'
        f'  <div class="cite">{cites:,} citations · seminal</div>'
        f'  <div class="doi">doi:{doi}</div>'
        f'</div>'
    )


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: compose.py recent.json throwback.json", file=sys.stderr)
        return 2

    recent = json.loads(Path(sys.argv[1]).read_text())
    throwback = json.loads(Path(sys.argv[2]).read_text())

    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()

    paper_blocks = "\n".join(fmt_paper(p, i + 1) for i, p in enumerate(recent))
    tb_html = fmt_throwback(throwback)

    style = (
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "sans-serif;max-width:640px;margin:1.5em auto;padding:0 1em;color:#222;"
        "line-height:1.45;}"
        "h1{font-size:1.4em;border-bottom:2px solid #0a4f8c;padding-bottom:.3em;}"
        "h2{font-size:1.05em;color:#0a4f8c;margin-top:1.6em;border-top:1px solid "
        "#ddd;padding-top:1em;}"
        ".paper{display:flex;gap:.8em;margin:1em 0;}"
        ".num{font-weight:600;color:#0a4f8c;min-width:1.5em;}"
        ".body{flex:1;}"
        ".title a{color:#0a4f8c;text-decoration:none;font-weight:600;}"
        ".title a:hover{text-decoration:underline;}"
        ".meta{font-size:.85em;color:#666;margin:.15em 0;}"
        ".why{font-size:.92em;margin:.3em 0;}"
        ".doi{font-size:.78em;color:#888;font-family:monospace;}"
        ".throwback{background:#fff8e1;border-left:3px solid #c89614;"
        "padding:.8em 1em;border-radius:4px;margin:1em 0;}"
        ".cite{font-size:.85em;color:#555;margin:.2em 0;}"
        ".footer{font-size:.8em;color:#888;margin-top:2em;border-top:1px "
        "solid #ddd;padding-top:.8em;}"
    )

    doc = (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<title>Multi-Omics Weekly · {iso_year}-W{iso_week:02d}</title>'
        f'<style>{style}</style></head><body>'
        f'<h1>Multi-Omics Weekly · {iso_year}-W{iso_week:02d}</h1>'
        f'<p>This week in multi-omics methods and multimodal AI in biology — '
        f'{len(recent)} papers + 1 throwback.</p>'
        f'<h2>This week</h2>'
        f'{paper_blocks}'
        f'<h2>This week in history</h2>'
        f'{tb_html}'
        f'<div class="footer">'
        f'Sources: OpenAlex (queried {today.isoformat()}). Reply with feedback '
        f'or topics to add/drop.<br>— Multi-Omics Group @ Technion'
        f'</div></body></html>'
    )
    sys.stdout.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
