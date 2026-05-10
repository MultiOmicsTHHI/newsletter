#!/usr/bin/env python3
"""Pick a 'this week in history' seminal paper.

Looks at the same ISO calendar week in past years (5–30 yrs back),
filters to ≥500 citations and biological relevance, randomly samples one.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())
STATE_PATH = ROOT / "state.json"

BIO_TITLE_KEYWORDS = [
    "biolog", "genom", "transcript", "protein", "epigen", "metabolom",
    "proteom", "microbio", "microbiom", "neuron", "neural network",
    "cancer", "tumor", "tumour", "immun", "antibod", "vaccin",
    "epigenetic", "methylation", "chromatin", "single-cell", "single cell",
    "mrna", "ncrna", "lncrna", "mirna", "splicing", "regulome",
    "phenotype", "genotype", "gwas", "cancer cell", "stem cell",
    "crispr", "gene therapy", "gene expression", "differential expression",
    "regulatory network", "signaling pathway",
]

BIO_VENUE_ALLOWLIST = [
    # Big-five science journals (often have life-science papers)
    "nature", "science", "cell", "lancet", "nejm",
    "new england journal of medicine", "proceedings of the national academy",
    "pnas",
    # Biology / biomedical specialists
    "biolog", "genom", "bioinf", "biotechn", "medicine", "medical",
    "physiology", "physiological", "neuro", "immunol", "cancer",
    "oncolog", "clinic", "pathol", "genet", "molecular",
    "proteom", "metabol", "microbiol", "virol", "cell host",
    "cell systems", "cell reports", "cell metab", "ebiomedicine",
    "elife", "embo", "cell biolog", "cancer biolog", "cancer cell",
    "cancer research", "developmental cell", "structure", "stem cell",
    "evolutionary", "epigenetics", "rna ", "dna ", "blood",
    "diabetes", "cardiovascular", "neurosci",
    # Bio-tagged repositories
    "biorxiv", "medrxiv", "arxiv", "q-bio",
]


def has_bio_signal(text: str) -> bool:
    return any(kw in text for kw in BIO_TITLE_KEYWORDS)


def venue_is_biological(venue: str) -> bool:
    return any(h in venue for h in BIO_VENUE_ALLOWLIST)


NON_BIO_VENUE_BLOCK = [
    "nuclear", "physics", "astron", "astrophys", "geophys", "engineer",
    "material", "chemic", "polymer", "petroleum", "industrial",
    "mathemati", "comput", "manuf", "mechan", "electric", "energy",
    "fuel", "construction", "civil",
]


def venue_is_blocked(venue: str) -> bool:
    return any(b in venue for b in NON_BIO_VENUE_BLOCK)


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"seen_dois": [], "seen_throwbacks": []}


def fetch_window(from_date: str, to_date: str, min_cites: int = 500) -> list[dict]:
    url = "https://api.openalex.org/works"
    params = {
        "filter": (
            f"from_publication_date:{from_date},"
            f"to_publication_date:{to_date},"
            f"cited_by_count:>{min_cites},"
            "type:article|review"
        ),
        "per-page": 50,
        "sort": "cited_by_count:desc",
        "select": (
            "id,doi,title,authorships,publication_year,publication_date,"
            "primary_location,cited_by_count,type"
        ),
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])


def is_biological(paper: dict) -> bool:
    title = (paper.get("title") or "").lower()
    pl = paper.get("primary_location") or {}
    src = pl.get("source") or {}
    venue = (src.get("display_name") or "").lower()
    if venue_is_blocked(venue):
        return False
    if not venue_is_biological(venue):
        return False
    return has_bio_signal(title) or venue_is_biological(venue)


def authors_string(paper: dict) -> str:
    a = paper.get("authorships", []) or []
    if not a:
        return ""
    first = (a[0].get("author") or {}).get("display_name", "") or ""
    if len(a) == 1:
        return first
    return f"{first} et al."


def venue_string(paper: dict) -> str:
    pl = paper.get("primary_location") or {}
    src = pl.get("source") or {}
    return src.get("display_name") or "Unknown venue"


def main() -> int:
    state = load_state()
    seen = set(state.get("seen_throwbacks", []))

    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()

    min_age = CONFIG.get("throwback_min_age_years", 5)
    max_age = CONFIG.get("throwback_max_age_years", 30)
    min_cites = CONFIG.get("throwback_min_cites", 500)

    candidates: list[dict] = []
    for years_back in range(min_age, max_age + 1):
        target_year = iso_year - years_back
        try:
            week_start = dt.date.fromisocalendar(target_year, iso_week, 1)
        except ValueError:
            continue
        week_end = week_start + dt.timedelta(days=6)
        try:
            papers = fetch_window(
                week_start.isoformat(), week_end.isoformat(), min_cites=min_cites,
            )
        except Exception as e:
            print(f"warn: year {target_year} week {iso_week} failed: {e}", file=sys.stderr)
            continue
        for p in papers:
            if not is_biological(p):
                continue
            doi = (p.get("doi") or "").replace("https://doi.org/", "")
            if not doi or doi in seen:
                continue
            candidates.append(p)

    print(f"info: {len(candidates)} biology candidates across years", file=sys.stderr)
    if not candidates:
        json.dump(None, sys.stdout)
        return 0

    methods_keywords = (
        "method", "framework", "benchmark", "tool", "pipeline", "algorithm",
        "atlas", "database", "platform", "package", "software", "deep learning",
        "neural network", "machine learning", "integration", "analysis",
        "model", "predict",
    )

    def is_methods_paper(p: dict) -> bool:
        title = (p.get("title") or "").lower()
        return any(k in title for k in methods_keywords)

    weights = []
    for p in candidates:
        cites = p.get("cited_by_count", 0)
        w = 1.0 + (cites / 5000.0)
        if is_methods_paper(p):
            w *= 1.5
        weights.append(w)

    pick = random.choices(candidates, weights=weights, k=1)[0]
    doi = (pick.get("doi") or "").replace("https://doi.org/", "")
    out = {
        "doi": doi,
        "title": (pick.get("title") or "").strip(),
        "year": pick.get("publication_year"),
        "date": pick.get("publication_date") or "",
        "venue": venue_string(pick),
        "authors": authors_string(pick),
        "cited_by_count": pick.get("cited_by_count", 0),
        "url": f"https://doi.org/{doi}" if doi else "",
    }
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
