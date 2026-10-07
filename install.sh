#!/usr/bin/env bash
# Installation locale de l'espace de travail ai-cycling-coach. Idempotent, sans effet hors du dépôt.
#   ./install.sh            agents + skills pour Claude Code, OpenCode, Copilot ; .mcp.json (Garmin, push seul)
#   ./install.sh --cron     affiche (sans l'installer) les lignes cron du daily-sync
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

link_dir() { # $1 = dossier cible (ex. .claude/agents) ; $2 = source relative depuis ce dossier
  mkdir -p "$1"
  local d
  for src in $3; do
    d="$1/$(basename "$src")"
    rm -rf "$d"
    ln -s "$2/$(basename "$src")" "$d"
  done
}

for ide in .claude .opencode; do
  link_dir "$ide/agents" "../../agents" "agents/*.md"
  link_dir "$ide/skills" "../../skills" "skills/*"
done
link_dir ".github/agents" "../../agents" "agents/*.md"
link_dir ".github/skills" "../../skills" "skills/*"

mkdir -p activities medical nutrition planning rapports resources logs

if [ ! -f .mcp.json ]; then
  cat > .mcp.json <<'JSON'
{
  "mcpServers": {
    "garmin": {
      "command": "garmin-mcp",
      "args": ["stdio"],
      "env": {
        "GARMIN_ENABLED_TOOLS": "schedule_workouts,schedule_week,upload_workout,get_scheduled_workouts,get_workout_by_id,get_workouts,unschedule_workout,unschedule_workouts,delete_workout,create_strength_workout"
      }
    }
  }
}
JSON
  echo "→ .mcp.json créé (Garmin : outils de PUSH seulement)"
fi

[ -f config/workspace.user.toml ] || {
  printf '# Overrides personnels (gitignoré). Voir config/workspace.toml.\n' > config/workspace.user.toml
  echo "→ config/workspace.user.toml créé"
}

echo
echo "Prochaines étapes :"
echo "  1. Connecte le MCP Open Wearables à ta session (connecteur claude.ai ou serveur MCP local)."
echo "  2. Installe garmin-mcp et authentifie-le (sert uniquement à pousser des entraînements)."
echo "  3. Dans Claude Code : /coach-setup"
echo "  4. python3 scripts/coach_doctor.py"

if [ "${1:-}" = "--cron" ]; then
  echo
  echo "# Lignes cron à ajouter vous-même (crontab -e) :"
  echo "15 7 * * *  $ROOT/scripts/daily-sync.sh"
  echo "30 20 * * * $ROOT/scripts/daily-sync.sh"
fi
