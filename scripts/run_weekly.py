#!/usr/bin/env python3
"""Weekly orchestrator: fetch → throwback → summarize → compose → send.

Updates state.json with sent DOIs and last-run timestamp on success.
Modes via env var NEWSLETTER_MODE:
  - send  (default for cron)
  - draft (saves draft.eml, doesn't send)
  - dry   (no API calls beyond fetching, no send)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "out"
ARCHIVE = ROOT / "archive"
RUNS = ROOT / "runs"
STATE_PATH = ROOT / "state.json"


def run(cmd: list[str], outfile: Path | None = None) -> None:
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    if outfile:
        with outfile.open("w") as f:
            r = subprocess.run(cmd, stdout=f, stderr=sys.stderr, check=False)
    else:
        r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {cmd}")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    ARCHIVE.mkdir(exist_ok=True)
    RUNS.mkdir(exist_ok=True)

    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    issue_id = f"{iso_year}-W{iso_week:02d}"

    mode = os.environ.get("NEWSLETTER_MODE", "send")

    py = sys.executable
    recent = OUT / "recent.json"
    throwback = OUT / "throwback.json"
    rendered = ARCHIVE / f"{issue_id}.html"

    # 1. fetch
    run([py, str(SCRIPTS / "fetch_recent.py")], outfile=recent)

    # 2. throwback
    run([py, str(SCRIPTS / "pick_throwback.py")], outfile=throwback)

    # 3. summarize (in place — modifies recent.json + throwback.json)
    run([py, str(SCRIPTS / "summarize.py"), str(recent), str(throwback)])

    # 4. compose
    run([py, str(SCRIPTS / "compose.py"), str(recent), str(throwback)], outfile=rendered)

    # 5. send (or draft / dry)
    run([py, str(SCRIPTS / "send.py"), str(rendered), mode])

    # 6. update state on success
    state = json.loads(STATE_PATH.read_text())
    seen_dois = set(state.get("seen_dois", []))
    seen_throwbacks = set(state.get("seen_throwbacks", []))
    issues_sent = state.get("issues_sent", [])

    for p in json.loads(recent.read_text()):
        if p.get("doi"):
            seen_dois.add(p["doi"])
    tb = json.loads(throwback.read_text())
    if tb and tb.get("doi"):
        seen_throwbacks.add(tb["doi"])

    if mode == "send":
        issues_sent.append({"issue": issue_id, "ts": dt.datetime.now(dt.timezone.utc).isoformat()})

    STATE_PATH.write_text(json.dumps({
        "seen_dois": sorted(seen_dois),
        "seen_throwbacks": sorted(seen_throwbacks),
        "last_run": dt.datetime.now(dt.timezone.utc).isoformat(),
        "issues_sent": issues_sent,
    }, indent=2))

    log_path = RUNS / f"{issue_id}.log"
    log_path.write_text(f"completed {dt.datetime.now(dt.timezone.utc).isoformat()} mode={mode}\n")
    print(f"info: issue {issue_id} done (mode={mode})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
