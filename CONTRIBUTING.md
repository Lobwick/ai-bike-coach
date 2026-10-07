# Contribuer

- Stdlib Python ≥ 3.9 uniquement ; pas de dépendance à installer.
- Un changement de comportement des scripts = un test dans `tests/test_core.py`
  (`python3 -m unittest discover -s tests`).
- `agents/` et `skills/` sont la source ; les dossiers `.claude/`, `.opencode/`, `.github/agents|skills`
  sont générés par `./install.sh` (liens symboliques).
- Aucune donnée personnelle dans le dépôt (`activities/`, `medical/`, `nutrition/`, `planning/`,
  `rapports/`, `resources/` sont gitignorés). Fixtures synthétiques seulement.
- Données lues via Open Wearables, jamais depuis Garmin ; Garmin = push seul.
- Pas de sigles déposés (TSS, CTL, ATL, TSB) dans les agents, skills ou fichiers.
