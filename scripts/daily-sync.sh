#!/usr/bin/env bash
# Synchronisation quotidienne headless : lance /daily-sync dans Claude Code.
# Lecture Open Wearables, jamais d'écriture Garmin. Voir skills/daily-sync/SKILL.md.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="logs/daily-sync-$(date +%Y-%m-%d).log"
RUNNER="$(python3 scripts/coach_config.py get sync.runner 2>/dev/null || echo claude)"

if [ "$RUNNER" != "claude" ]; then
  echo "runner « $RUNNER » non pris en charge (seul « claude » l'est)" | tee -a "$LOG"
  exit 2
fi
command -v claude >/dev/null || { echo "claude introuvable dans le PATH" | tee -a "$LOG"; exit 2; }

{
  echo "=== $(date '+%F %T') daily-sync ==="
  claude -p "/daily-sync" --permission-mode acceptEdits
} >> "$LOG" 2>&1 || { echo "daily-sync en échec, voir $LOG" >&2; exit 1; }

if [ "$(python3 scripts/coach_config.py get sync.git_autocommit 2>/dev/null)" = "true" ] \
   && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git add -A && git commit -qm "chore: daily-sync $(date +%F)" && git push -q || true
fi
