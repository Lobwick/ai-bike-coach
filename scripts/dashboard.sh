#!/usr/bin/env bash
# Lance le tableau de bord local (lecture seule, 127.0.0.1). Ctrl-C pour arrêter.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec python3 scripts/arc_serve.py "$@"
