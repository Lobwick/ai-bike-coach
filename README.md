# AI Cycling Coach

Coaching IA **vélo de route**, **cyclo-cross** et **perte de poids**, dans un espace de travail 100 % fichiers
Markdown. Dérivé de [`mmornati/ai-running-coach`](https://github.com/mmornati/ai-running-coach).

- 🔎 **Lit** tes données via le MCP **Open Wearables** (Garmin, Whoop, Apple Santé, Strava… agrégés).
- 🩸 **Glycémie** (optionnel) : lecture seule via **Nightscout** — contrôle avant séance, analyse pendant/après, hypoglycémies tardives ; jamais de dose ni d'écriture. `/override` analyse tes préréglages Loop et propose des hypothèses de réglage (ou un nouveau préréglage) à appliquer toi-même dans Loop.
- 📤 **Pousse** tes entraînements sur **Garmin Connect** — seul rôle de Garmin ici.
- 🤖 5 agents : `coach-route`, `coach-cx`, `coach-poids`, `medical`, `nutritionist`.
- 🛡 Garde-fous déterministes (rampe de charge, jours durs, perte de poids trop rapide, déficit un jour clé).

## Démarrage

```bash
./install.sh                         # liens agents/skills (Claude Code, OpenCode, Copilot) + .mcp.json
python3 scripts/coach_doctor.py      # diagnostic
claude                               # puis /coach-setup
```

Prérequis : Python ≥ 3.9 (aucune dépendance), un connecteur **Open Wearables** actif dans la session,
`garmin-mcp` installé et authentifié (pour pousser seulement).

## Commandes

`/coach-setup` · `/today` · `/week` · `/log` · `/daily-sync` (headless, cron) · `/coach-doctor`.
Exemples : « construis-moi un bloc de 8 semaines pour une cyclosportive en juin », « prépare ma semaine de
cyclo-cross avec course dimanche », « je veux perdre 5 kg d'ici février sans casser mes séances ».

## Limites connues (dites, jamais comblées)

- Les séances Open Wearables n'ont **pas de puissance** : la charge vient de la série de FC (la meilleure option, FC repos/max
  requises), puis de la FC moyenne, puis du RPE, sauf puissance déclarée. Les séries d'énergie horaires ne sont pas fiables : seul le total
  quotidien l'est, et un `0` y signifie « absent ». Plus le profil (FTP, LTHR, FC max/repos) est complet, meilleure est l'estimation.
- Les **doublons** entre sources (devenus rares) sont éliminés par `arc_ow.py` ; une séance englobée par un bloc plus long
  (ex. fenêtre Whoop couvrant deux sorties) est listée mais non comptée.
- Les **cibles de puissance** Garmin (`power.zone`) doivent être vérifiées au premier push.
- Seuils de garde-fou et zones sont des « approximations du projet », pas un avis médical.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Licence : voir `LICENSE`.
