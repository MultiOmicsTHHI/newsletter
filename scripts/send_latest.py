#!/usr/bin/env python3
"""Autonomously send the latest rendered newsletter issue via SMTP.

The weekly cron defaults to `draft` mode and waits for a human to click Send.
This script is the unattended counterpart: it picks the most recent rendered
issue and delivers it end-to-end with no manual step.

    python3 scripts/send_latest.py            # send newest archive/*.html
    python3 scripts/send_latest.py 2026-W23   # send a specific issue id
    python3 scripts/send_latest.py path.html  # send a specific file
    python3 scripts/send_latest.py --dry      # show what would be sent

Requires GMAIL_APP_PASSWORD (or SMTP_PASSWORD) in secrets.env; exits non-zero
if delivery fails so a scheduler can detect it. Reuses send.py for the SMTP
machinery and message building.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import send  # scripts/ is on sys.path[0] when run as a script

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "archive"
ISSUE_RE = re.compile(r"(\d{4})-W(\d{2})")


def latest_issue() -> Path | None:
    candidates = [p for p in ARCHIVE.glob("*.html") if "_dryrun" not in p.stem]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def resolve(arg: str | None) -> Path | None:
    if not arg:
        return latest_issue()
    p = Path(arg)
    if p.exists():
        return p
    cand = ARCHIVE / f"{arg}.html"  # treat bare arg as an issue id, e.g. 2026-W23
    return cand if cand.exists() else None


def main() -> int:
    rest = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv[1:]

    issue = resolve(rest[0] if rest else None)
    if issue is None:
        print("send_latest: no rendered issue found in archive/", file=sys.stderr)
        return 2

    send.load_secrets()
    msg = send.build_message(issue.read_text())

    # build_message derives the subject from today's date; for a named issue
    # file, label the subject from the filename so it stays accurate.
    m = ISSUE_RE.search(issue.stem)
    if m:
        tmpl = send.CONFIG.get("email", {}).get(
            "subject_template", "Multi-Omics Weekly · {year}-W{week:02d}"
        )
        del msg["Subject"]
        msg["Subject"] = tmpl.format(year=int(m.group(1)), week=int(m.group(2)))

    if dry:
        print(f"[dry] would send {issue.name}: {msg['Subject']!r} -> {msg['To']}",
              file=sys.stderr)
        return 0

    try:
        send.send_via_smtp(msg)
        print(f"[send] delivered {issue.name} to {msg['To']}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"[send] FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
