#!/usr/bin/env bash
# Copie tes fichiers personnels du Mac vers la Freebox (qui devient la source de vérité) et initialise le dépôt git privé.
# SIMULATION par défaut ; `--yes` pour exécuter. Ne supprime rien côté Mac, n'efface rien côté Freebox (rsync sans --delete).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${FREEBOX_SSH:?définis FREEBOX_SSH, ex. FREEBOX_SSH=utilisateur@ip-de-la-freebox}"
DEST="${DATA_DIR:-coach-data}"      # relatif au dossier personnel distant ; DATA_DIR de .env doit pointer vers le même dossier (chemin absolu)
DIRS=(activities medical nutrition planning rapports resources)
RS=(-a --itemize-changes --exclude='.DS_Store' --exclude='*.tmp' --exclude='.arc-*')
[ "${1:-}" = "--yes" ] || RS+=(--dry-run)

echo "Source : $ROOT  →  $REMOTE:$DEST   ($([ "${1:-}" = "--yes" ] && echo EXÉCUTION || echo simulation))"
ssh "$REMOTE" "mkdir -p '$DEST/config' $(printf "'$DEST/%s' " "${DIRS[@]}")"
for d in "${DIRS[@]}"; do
  [ -d "$ROOT/$d" ] && rsync "${RS[@]}" "$ROOT/$d/" "$REMOTE:$DEST/$d/"
done
[ -f "$ROOT/config/workspace.user.toml" ] && rsync "${RS[@]}" "$ROOT/config/workspace.user.toml" "$REMOTE:$DEST/config/workspace.user.toml"

if [ "${1:-}" = "--yes" ]; then
  ssh "$REMOTE" "cd '$DEST' && { [ -d .git ] || git init -q; } && git config user.name 'Coach' && git config user.email 'coach@local' \
    && printf '%s\n' '.DS_Store' '*.tmp' '.arc-*' > .gitignore && git add -A && { git diff --cached --quiet || git commit -q -m 'import depuis le Mac'; } && git log --oneline | head -3"
  echo "OK. Étape suivante : cd deploy/freebox, remplir .env, puis docker compose up -d --build (voir README.md)."
else
  echo "Simulation terminée : relance avec --yes pour copier."
fi
