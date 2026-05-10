#!/usr/bin/env bash
# Weekly Multi-Omics newsletter run.
# Invoked by Windows Task Scheduler:
#   wsl.exe -d Ubuntu-24.04 -- /home/ozsol/newsletter/cron.sh
# Default mode: draft (saves HTML + .eml without sending).
# Override: set NEWSLETTER_MODE=send|draft|dry before invoking.

set -euo pipefail

# Make sure HOME/PATH are sane when launched by Windows Task Scheduler
export HOME="${HOME:-/home/ozsol}"
export PATH="$HOME/miniconda3/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

cd "$HOME/newsletter"

LOGDIR="$HOME/newsletter/runs"
mkdir -p "$LOGDIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$LOGDIR/run-$TS.log"

MODE="${NEWSLETTER_MODE:-draft}"

{
    echo "=== run started $(date -Is) (mode=$MODE) ==="
    NEWSLETTER_MODE="$MODE" python3 scripts/run_weekly.py
    rc=$?
    echo "=== run completed $(date -Is) rc=$rc ==="

    # On success, pop the draft .eml into the user's default Windows mail
    # app so they only need to click Send.
    if [ "$rc" -eq 0 ] && [ -f "$HOME/newsletter/out/draft.eml" ]; then
        win_path=$(wslpath -w "$HOME/newsletter/out/draft.eml")
        echo "opening: $win_path"
        explorer.exe "$win_path" >/dev/null 2>&1 || true
    fi
} >>"$LOG" 2>&1

# Keep the most recent 20 logs
ls -1t "$LOGDIR"/run-*.log 2>/dev/null | tail -n +21 | xargs -r rm -f
