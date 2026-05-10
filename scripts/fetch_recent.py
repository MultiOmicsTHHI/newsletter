#!/usr/bin/env python3
"""Fetch recent multi-omics / multimodal-AI biology papers from OpenAlex.

Reads ../config.yaml, queries OpenAlex per topic, dedupes by DOI against
state.json, ranks by venue tier + keyword match, writes the top-N as JSON
to stdout.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())
STATE_PATH = ROOT / "state.json"

VENUE_TIER: dict[str, int] = {
    "Nature": 5, "Science": 5, "Cell": 5, "New England Journal of Medicine": 5,
    "The Lancet": 5,
    "Nature Methods": 4, "Nature Biotechnology": 4, "Nature Communications": 4,
    "Nature Cell Biology": 4, "Nature Machine Intelligence": 4,
    "Nature Genetics": 4, "Nature Medicine": 4, "Nature Reviews Genetics": 4,
    "Cell Systems": 4, "Cancer Cell": 4, "Molecular Cell": 4,
    "PNAS": 4, "Proceedings of the National Academy of Sciences": 4,
    "Genome Biology": 3, "Genome Medicine": 3,
    "Briefings in Bioinformatics": 3, "Nucleic Acids Research": 3,
    "Bioinformatics": 3, "NAR Genomics and Bioinformatics": 3,
    "Cell Reports": 3, "Cell Reports Methods": 3, "iScience": 3,
    "PLOS Computational Biology": 3, "PLOS Biology": 3,
    "BMC Bioinformatics": 2, "Scientific Reports": 2, "BioData Mining": 2,
    "Frontiers in Genetics": 2, "Frontiers in Bioinformatics": 2,
}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"seen_dois": [], "seen_throwbacks": []}


def fetch_openalex(query: str, from_date: str, per_page: int = 25) -> list[dict]:
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "filter": f"from_publication_date:{from_date}",
        "per-page": per_page,
        "sort": "publication_date:desc",
        "select": (
            "id,doi,title,authorships,publication_year,publication_date,"
            "primary_location,cited_by_count,abstract_inverted_index,type"
        ),
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])


def reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    pos_word: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for p in positions:
            pos_word[p] = word
    return " ".join(pos_word[k] for k in sorted(pos_word))


def venue_tier(venue_name: str, source_type: str) -> int:
    if source_type == "repository":
        return 1
    return VENUE_TIER.get(venue_name, 2)


INTEGRATION_TERMS = {
    "multi-omics", "multiomics", "multi-modal", "multimodal",
    "data fusion", "joint analysis", "joint modeling", "joint modelling",
    "data integration",
}

OMICS_TERMS = {
    "omics", "proteom", "transcriptom", "metabolom", "epigenom",
    "lipidom",
}

ML_TERMS = {
    "deep learning", "neural network", "machine learning",
    "transformer", "autoencoder", "graph neural", "foundation model",
    "generative model", "variational", "self-supervised",
    "diffusion model",
}

METHOD_TITLE_TERMS = {
    "method", "framework", "benchmark", "tool", "pipeline",
    "algorithm", "architecture", "platform", "toolkit", "model",
}


def get_text(paper: dict) -> tuple[str, str]:
    title = (paper.get("title") or "").lower()
    abstract = reconstruct_abstract(paper.get("abstract_inverted_index")).lower()
    return title, abstract


def is_in_scope(paper: dict) -> bool:
    """Paper must hit at least one of three on-topic patterns:
    (a) multi-omics: integration term + omics term
    (b) multimodal AI in biology: integration term + ML term
    (c) omics methods: omics term + ML term
    """
    title, abstract = get_text(paper)
    text = title + " " + abstract
    has_integration = any(t in text for t in INTEGRATION_TERMS)
    has_omics = any(t in text for t in OMICS_TERMS)
    has_ml = any(t in text for t in ML_TERMS)
    return (
        (has_integration and has_omics) or
        (has_integration and has_ml) or
        (has_omics and has_ml)
    )


ALLOWED_TYPES = {"article", "review", "preprint"}
EXCLUDED_VENUES = {
    "zenodo", "figshare", "dryad", "osf", "research square", "ssrn",
    "preprints.org",
}


def is_research_paper(paper: dict) -> bool:
    """Filter out datasets, conference proceedings, posters, and Zenodo deposits."""
    if (paper.get("type") or "").lower() not in ALLOWED_TYPES:
        return False
    pl = paper.get("primary_location") or {}
    src = pl.get("source") or {}
    venue = (src.get("display_name") or "").lower()
    if any(bad in venue for bad in EXCLUDED_VENUES):
        return False
    return True


def score_paper(paper: dict) -> int:
    pl = paper.get("primary_location") or {}
    src = pl.get("source") or {}
    venue_name = src.get("display_name", "") or ""
    src_type = src.get("type", "") or ""
    tier = venue_tier(venue_name, src_type)
    title, abstract = get_text(paper)
    text = title + " " + abstract

    methods_in_title = any(m in title for m in METHOD_TITLE_TERMS)
    has_integration = any(t in text for t in INTEGRATION_TERMS)
    has_ml = any(t in text for t in ML_TERMS)
    has_omics = any(t in text for t in OMICS_TERMS)
    multi_in_title = any(m in title for m in ("multi-omics", "multiomics", "multimodal", "multi-modal"))

    s = tier * 4
    if methods_in_title:
        s += 10
    if multi_in_title:
        s += 8
    if has_integration:
        s += 6
    if has_ml:
        s += 4
    if has_omics:
        s += 2
    return s


def authors_string(paper: dict) -> str:
    a = paper.get("authorships", []) or []
    if not a:
        return ""
    first = (a[0].get("author") or {}).get("display_name", "") or ""
    if len(a) == 1:
        return first
    return f"{first} et al."


SUSPICIOUS_VENUES = {"pubmed", "lepidopt", "shilap"}


def crossref_venue(doi: str) -> str | None:
    if not doi:
        return None
    try:
        r = requests.get(
            f"https://api.crossref.org/works/{doi}",
            timeout=15,
            headers={"User-Agent": "multiomics-newsletter (mailto:bioinfo.multiomics@technion.ac.il)"},
        )
        r.raise_for_status()
        data = r.json().get("message", {})
        ct = data.get("container-title") or []
        if ct:
            return ct[0]
    except Exception:
        return None
    return None


def venue_string(paper: dict) -> str:
    pl = paper.get("primary_location") or {}
    src = pl.get("source") or {}
    name = src.get("display_name") or ""
    nl = name.lower()
    if not name or any(s in nl for s in SUSPICIOUS_VENUES):
        doi = (paper.get("doi") or "").replace("https://doi.org/", "")
        cr = crossref_venue(doi)
        if cr:
            return cr
        return name or "Preprint"
    return name


def main() -> int:
    state = load_state()
    seen = set(state.get("seen_dois", []))

    today = dt.date.today()
    days = CONFIG.get("recency_days", 14)
    from_date = (today - dt.timedelta(days=days)).isoformat()

    queries = CONFIG.get("queries", [])
    keywords = CONFIG.get("keywords", [])

    all_papers: dict[str, dict] = {}
    for q in queries:
        try:
            papers = fetch_openalex(q, from_date)
        except Exception as e:
            print(f"warn: query {q!r} failed: {e}", file=sys.stderr)
            continue
        for p in papers:
            doi = (p.get("doi") or "").replace("https://doi.org/", "")
            if not doi or doi in seen or doi in all_papers:
                continue
            if not is_research_paper(p):
                continue
            if not is_in_scope(p):
                continue
            all_papers[doi] = p

    ranked = sorted(all_papers.values(), key=score_paper, reverse=True)
    top_n = CONFIG.get("papers_per_issue", 6)

    out = []
    for p in ranked[:top_n]:
        doi = (p.get("doi") or "").replace("https://doi.org/", "")
        out.append({
            "doi": doi,
            "title": (p.get("title") or "").strip(),
            "venue": venue_string(p),
            "date": p.get("publication_date") or "",
            "authors": authors_string(p),
            "abstract": reconstruct_abstract(p.get("abstract_inverted_index"))[:600],
            "url": f"https://doi.org/{doi}" if doi else "",
            "score": score_paper(p),
        })

    print(f"info: {len(all_papers)} candidates, top {len(out)} selected", file=sys.stderr)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
