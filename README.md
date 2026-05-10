# newsletter

Weekly **Multi-Omics** newsletter generator. Pulls recent papers from OpenAlex,
picks a "throwback" classic, summarizes with an LLM, renders an HTML email,
and either sends it via Gmail SMTP or saves a draft `.eml`.

## Pipeline

```
fetch_recent.py  →  pick_throwback.py  →  summarize.py  →  compose.py  →  send.py
   (OpenAlex)        (classic paper)       (LLM blurbs)     (HTML)        (SMTP / draft)
```

`scripts/run_weekly.py` orchestrates all five stages and updates `state.json`
(seen DOIs, sent issues) on success.

## Setup

```bash
cp secrets.env.example secrets.env
# edit secrets.env: set LLM_PROVIDER + matching API key, plus GMAIL_APP_PASSWORD
pip install requests pyyaml
```

Configure topics, recency window, throwback constraints, and email metadata in
`config.yaml`.

## Run

```bash
NEWSLETTER_MODE=draft python3 scripts/run_weekly.py   # save .eml, no send
NEWSLETTER_MODE=send  python3 scripts/run_weekly.py   # send via SMTP
NEWSLETTER_MODE=dry   python3 scripts/run_weekly.py   # no LLM/send
```

Default mode in `cron.sh` is `draft`.

## Scheduled runs (WSL + Windows Task Scheduler)

`cron.sh` is invoked by Windows Task Scheduler:

```
wsl.exe -d Ubuntu-24.04 -- /home/ozsol/newsletter/cron.sh
```

It writes per-run logs to `runs/`, keeps the latest 20, and on success opens
`out/draft.eml` in the default Windows mail app so the issue can be reviewed
and sent with one click.

## Layout

| Path | Purpose |
|---|---|
| `config.yaml` | Topics, recency, throwback rules, email fields |
| `secrets.env` | API keys + SMTP password (git-ignored) |
| `scripts/` | Pipeline stages + orchestrator |
| `cron.sh` | Weekly entry point for Task Scheduler |
| `out/` | Latest run's `recent.json`, `throwback.json`, `draft.eml` (git-ignored) |
| `archive/` | Rendered HTML per issue, e.g. `2026-W19.html` (git-ignored) |
| `runs/` | Per-run logs (git-ignored) |
| `state.json` | Seen DOIs and issue history (git-ignored) |

## LLM providers

`LLM_PROVIDER` in `secrets.env` selects the summarizer backend:
`claude_cli` (default), `anthropic`, `openai`, `perplexity`, or `none`.
For OpenAI-compatible gateways (OpenRouter, Together, Groq) set `LLM_BASE_URL`.
