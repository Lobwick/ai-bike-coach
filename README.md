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

## Tableau de bord

```bash
./scripts/dashboard.sh        # http://127.0.0.1:8765/ — lecture seule, local, aucune dépendance
```
Même identité visuelle que le tableau de bord d'origine (compte à rebours de la prochaine course, navigation latérale, thème clair/sombre).
Vues : Aujourd'hui, Forme & charge, Santé, Semaine, Séances, Calendrier, Décisions, Poids. Elles affichent ce que les agents ont **déjà
enregistré** dans tes fichiers (séances, bilans, glycémie, plan). N'écoute que sur `127.0.0.1`, n'interroge ni Open Wearables, ni
Nightscout, ni Garmin, n'écrit rien. Seule requête externe : les polices Sora/Inter (Google Fonts, adresse IP visible de Google) ;
`[dashboard].web_fonts = false` les désactive.

## Accès depuis le mobile (optionnel, Freebox / serveur perso)

`deploy/freebox/` déploie derrière Traefik le **site** (mot de passe) et une **API MCP** (jeton) qui laissent Claude mobile lire et modifier
le plan, le profil et les fichiers, avec validation du contrat, un commit git par écriture et un `undo`. Le site relit les fichiers
à chaque chargement (rechargement automatique) : rien à reconstruire. Voir `deploy/freebox/README.md`.

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
