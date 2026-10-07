#!/usr/bin/env bash
# Copie tes fichiers personnels du Mac vers la Freebox (qui devient la source de vérité) et initialise le dépôt git privé.
# SIMULATION par défaut ; `--yes` pour exécuter. Utilise tar à travers SSH (aucun rsync requis côté Freebox).
# Ne supprime rien (ni côté Mac, ni côté Freebox) et N'ÉCRASE AUCUN fichier déjà présent sur la Freebox (--skip-old-files) :
# sans danger à relancer, même quand le mobile a déjà écrit.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${FREEBOX_SSH:?définis FREEBOX_SSH, ex. FREEBOX_SSH=utilisateur@ip-de-la-freebox}"
DEST="${DATA_DIR:-coach-data}"      # relatif au dossier personnel distant ; DATA_DIR de .env doit pointer vers le même dossier (chemin absolu)
DIRS=(activities medical nutrition planning rapports resources)
export COPYFILE_DISABLE=1           # macOS : pas de fichiers ._* ni d'attributs étendus
EXCL=(--exclude='.DS_Store' --exclude='*.tmp' --exclude='.arc-*')

FILES=()
for d in "${DIRS[@]}"; do [ -d "$ROOT/$d" ] && FILES+=("$d"); done
[ -f "$ROOT/config/workspace.user.toml" ] && FILES+=("config/workspace.user.toml")

echo "Source : $ROOT  →  $REMOTE:$DEST   ($([ "${1:-}" = "--yes" ] && echo EXÉCUTION || echo simulation))"
N=$(tar -C "$ROOT" "${EXCL[@]}" -cf - "${FILES[@]}" | tar -tf - | grep -vc '/$' || true)
echo "À copier : $N fichier(s) dans : ${FILES[*]}"

if [ "${1:-}" = "--yes" ]; then
  tar -C "$ROOT" "${EXCL[@]}" -cf - "${FILES[@]}" | ssh "$REMOTE" "mkdir -p '$DEST/config' && tar -C '$DEST' --skip-old-files -xf -"
  ssh "$REMOTE" "cd '$DEST' && for d in ${DIRS[*]} config; do mkdir -p \$d; done && { [ -d .git ] || git init -q; } \
    && git config user.name 'Coach' && git config user.email 'coach@local' \
    && printf '%s\n' '.DS_Store' '*.tmp' '.arc-*' > .gitignore && git add -A && { git diff --cached --quiet || git commit -q -m 'import depuis le Mac'; } \
    && echo \"fichiers suivis : \$(git ls-files | wc -l)\" && git log --oneline | head -3"
  echo "OK. Étape suivante : cd deploy/freebox, remplir .env, puis docker compose up -d --build (voir README.md)."
else
  echo "Simulation terminée : relance avec --yes pour copier."
fi
