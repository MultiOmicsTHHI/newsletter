#!/usr/bin/env python3
"""Add per-paper "why it matters" summaries.

Provider is selected via LLM_PROVIDER in secrets.env (default: claude_cli):

  claude_cli  — invokes the local Claude Code CLI (`claude -p`), free under
                your existing Claude subscription. No API key needed.
  anthropic   — direct Anthropic API; needs ANTHROPIC_API_KEY.
  openai      — OpenAI-compatible (also Perplexity / OpenRouter); needs
                OPENAI_API_KEY (and optionally LLM_BASE_URL, LLM_MODEL).
  none        — extractive fallback: first sentences of the abstract.

If the chosen provider fails, falls back to extractive so the pipeline
still produces a usable issue.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets.env"


def load_secrets() -> None:
    if not SECRETS.exists():
        return
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


SYSTEM_PROMPT = (
    "You are a senior multi-omics scientist writing a weekly digest for a "
    "small bioinformatics group at Technion.\n\n"
    "For each paper input, output ONE short \"why it matters\" blurb:\n"
    "  [TAG] Sentence one. Sentence two.\n\n"
    "Rules:\n"
    "- TAG: a short bracketed label such as [VAE], [GNN], [foundation model], "
    "[benchmark], [proteomics], [methylation], [multimodal], [perturbation], "
    "[clinical], [methods].\n"
    "- Two sentences MAX, ~50 words total.\n"
    "- State concretely what the paper does AND why a multi-omics group should "
    "care.\n"
    "- No hype, no 'this paper', no marketing language, no 'importantly'.\n"
    "- Output ONLY the blurb. No preamble, no quotes, no extra commentary."
)


def build_user_text(paper: dict) -> str:
    return (
        f"Title: {paper.get('title','')}\n"
        f"Venue: {paper.get('venue','')} ({paper.get('date','') or paper.get('year','')})\n"
        f"Abstract: {paper.get('abstract','')}"
    )


# ---- providers ----------------------------------------------------------

_ANTHROPIC_BLOCKLIST = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_API_KEY", "CLAUDE_CODE_API_KEY",
)


def call_claude_cli(paper: dict) -> str:
    user_text = build_user_text(paper)
    full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{user_text}"
    # Strip API-key env vars so claude -p falls back to OAuth.
    child_env = {k: v for k, v in os.environ.items()
                 if k not in _ANTHROPIC_BLOCKLIST}
    try:
        r = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "text",
                "--model", "haiku",
                "--tools", "",
            ],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=120,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("claude_cli timeout")
    if r.returncode != 0:
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        raise RuntimeError(f"claude_cli rc={r.returncode}: {(err or out)[:400]}")
    return r.stdout.strip()


def call_anthropic(paper: dict, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model or "claude-haiku-4-5-20251001",
        max_tokens=180,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": build_user_text(paper)}],
    )
    return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()


def call_openai_compatible(paper: dict, model: str, base_url: str | None) -> str:
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("PERPLEXITY_API_KEY")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model or "gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_text(paper)},
        ],
        max_tokens=180,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


def extractive_fallback(paper: dict) -> str:
    abs_text = (paper.get("abstract") or "").strip()
    if not abs_text:
        return "[summary] (no abstract available)"
    sentences = re.split(r"(?<=[.!?])\s+", abs_text)
    blurb = " ".join(sentences[:2])
    return f"[abstract] {blurb}"


PROVIDERS = {
    "claude_cli": lambda p, m, b: call_claude_cli(p),
    "anthropic":  lambda p, m, b: call_anthropic(p, m),
    "openai":     lambda p, m, b: call_openai_compatible(p, m, b),
    "perplexity": lambda p, m, b: call_openai_compatible(p, m, b or "https://api.perplexity.ai"),
    "none":       lambda p, m, b: extractive_fallback(p),
}


def summarize_one(paper: dict, provider: str, model: str, base_url: str | None) -> str:
    fn = PROVIDERS.get(provider, PROVIDERS["claude_cli"])
    try:
        return fn(paper, model, base_url)
    except Exception as e:
        print(f"warn: provider {provider!r} failed: {e}", file=sys.stderr)
        return extractive_fallback(paper)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: summarize.py recent.json throwback.json", file=sys.stderr)
        return 2
    load_secrets()
    provider = os.environ.get("LLM_PROVIDER", "claude_cli").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip() or None
    print(f"info: provider={provider} model={model or '(default)'}", file=sys.stderr)

    recent_path = Path(sys.argv[1])
    throwback_path = Path(sys.argv[2])
    papers = json.loads(recent_path.read_text())
    tb = json.loads(throwback_path.read_text())

    for p in papers:
        p["why_it_matters"] = summarize_one(p, provider, model, base_url)
    if tb is not None:
        tb["why_it_matters"] = summarize_one(tb, provider, model, base_url)

    recent_path.write_text(json.dumps(papers, indent=2, ensure_ascii=False))
    if tb is not None:
        throwback_path.write_text(json.dumps(tb, indent=2, ensure_ascii=False))

    print(f"info: summarised {len(papers)} papers + {1 if tb else 0} throwback", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
