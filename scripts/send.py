#!/usr/bin/env python3
"""Send (or save as draft) the rendered newsletter HTML via Gmail SMTP.

Reads:
  - argv[1]: rendered HTML file
  - secrets.env (GMAIL_USER, GMAIL_APP_PASSWORD, optional ANTHROPIC_API_KEY)
  - config.yaml (email.to, email.from, email.subject_template)

Modes (argv[2], optional):
  - "send" (default): actually send via SMTP
  - "draft": render to plain-text + HTML and save to out/draft.eml without sending
  - "dry": print what would happen, do nothing
"""
from __future__ import annotations

import datetime as dt
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())
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


def html_to_text(html_doc: str) -> str:
    """Lightweight HTML→text fallback for the multipart/alternative."""
    txt = re.sub(r"<style[^>]*>.*?</style>", "", html_doc, flags=re.S | re.I)
    txt = re.sub(r"<script[^>]*>.*?</script>", "", txt, flags=re.S | re.I)
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
    txt = re.sub(r"</(p|div|h\d|li)>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt


def build_message(html_doc: str) -> MIMEMultipart:
    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    email_cfg = CONFIG.get("email", {})
    subject = email_cfg.get("subject_template", "Multi-Omics Weekly · {year}-W{week:02d}").format(
        year=iso_year, week=iso_week
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg["from"]
    msg["To"] = email_cfg["to"]
    msg.attach(MIMEText(html_to_text(html_doc), "plain", "utf-8"))
    msg.attach(MIMEText(html_doc, "html", "utf-8"))
    return msg


def send_via_smtp(msg: MIMEMultipart) -> None:
    user = os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER")
    pwd = (
        os.environ.get("SMTP_PASSWORD")
        or os.environ.get("GMAIL_APP_PASSWORD")
    )
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    security = os.environ.get("SMTP_SECURITY", "ssl").lower()  # ssl | starttls | none

    if not user or not pwd:
        raise RuntimeError("SMTP_USER/SMTP_PASSWORD (or GMAIL_*) missing in secrets.env")

    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
    elif security == "starttls":
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)


def write_draft(msg: MIMEMultipart, out_dir: Path) -> Path:
    """Write the .eml as an editable draft.

    The X-Unsent: 1 header makes Outlook/Windows Mail open the file as a new
    composed message (From the account, click Send → goes to Sent), instead of
    a read-only received message that has to be forwarded.
    """
    if "X-Unsent" not in msg:
        msg["X-Unsent"] = "1"
    draft_path = out_dir / "draft.eml"
    draft_path.write_bytes(msg.as_bytes())
    return draft_path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: send.py rendered.html [send|draft|dry]", file=sys.stderr)
        return 2
    html_path = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "send"
    load_secrets()

    html_doc = html_path.read_text()
    msg = build_message(html_doc)

    if mode == "dry":
        print(f"[dry] would send: {msg['Subject']!r} to {msg['To']}", file=sys.stderr)
        return 0

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)

    if mode == "draft":
        draft_path = write_draft(msg, out_dir)
        print(f"[draft] saved {draft_path}", file=sys.stderr)
        return 0

    if mode == "send":
        try:
            send_via_smtp(msg)
            print(f"[send] delivered to {msg['To']}", file=sys.stderr)
            return 0
        except Exception as e:
            print(f"[send] FAILED: {e} — falling back to draft", file=sys.stderr)
            write_draft(msg, out_dir)
            return 1

    print(f"unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
