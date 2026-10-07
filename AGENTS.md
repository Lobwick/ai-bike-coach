# AI Cycling Coach — Workspace

Espace de travail de coaching **vélo de route**, **cyclo-cross (CX)** et **perte de poids**. Les agents IA
planifient, analysent, et persistent tout en fichiers Markdown (français par défaut).

> Dérivé de `mmornati/ai-running-coach` (course à pied / trail), réécrit pour le vélo.
> L'ancien moteur (trail shape, GAP, pacing de course, chat, Telegram, index SQLite) a été retiré ; il reste dans
> l'historique git. Le tableau de bord a été **reconstruit** pour le vélo (voir `scripts/arc_serve.py`).

## Flux de données — la règle d'or

```
  Montres / capteurs (Garmin, Whoop, Apple, Strava…)
              │
              ▼
     MCP  OPEN WEARABLES  ──── LECTURE SEULE ────►  agents  ──►  fichiers .md (arc)
                                                       │
                                                       └── POUSSE les séances ──►  Garmin Connect (MCP garmin)
```

- **Toute lecture** (séances, sommeil, HRV, FC de repos, poids, cycle) passe par **Open Wearables**.
- **Glycémie** (opt-in, `[glucose].enabled`) : MCP **Nightscout**, **lecture seule**. Jamais `log_treatment`,
  `remove_treatment` ni `update_nightscout_profile` ; jamais de dose ni de réglage de basale/override Loop.
- **Garmin = écriture seule** : `schedule_workouts`, `schedule_week`, `upload_workout` (+ vérification
  `get_scheduled_workouts`/`get_workout_by_id` de ce qu'on a poussé). Aucun outil de lecture `garmin`
  n'est exposé (`.mcp.json`) ni utilisé. Jamais de push sans « oui » explicite, jamais en headless.
- Open Wearables agrège plusieurs sources (Apple, Strava, Whoop, Garmin…) : les doublons sont devenus rares mais pas
  nuls, tout passe donc par `scripts/arc_ow.py` (idempotent : dédoublonnage, enveloppes, calories par source, `0` =
  absent, FC d'une séance). Pas de puissance dans les données : la charge vient de la puissance **déclarée** > **série de
  FC** > FC moyenne > RPE, méthode toujours tracée.

## Configuration

Résolution : `config/workspace.toml` (versionné) puis `config/workspace.user.toml` (gitignoré, prime,
clé par clé ; une clé présente mais vide gagne). Lecture : `python3 scripts/coach_config.py get <clé>`.

| Clé | Effet |
|---|---|
| `[language].documents` / `.responses` | Langue des MD persistés / des réponses (`auto`). |
| `[coaching].style / intensity / verbosity` | Voix → `config/coaching-styles.md`. Le profil de l'athlète prime ; le style ne change jamais le fond. |
| `[sport].disciplines` | `route` · `cx` · `poids` → `config/sports/<id>.md`. `[sport].cross` = sports croisés. |
| `[agents].enabled` | **Seuls agents joignables.** Ne jamais déléguer à un agent absent. |
| `[data].source` / `.ow_user_id` / `.source_priority` | Open Wearables ; priorité des sources en cas de doublon. |
| `[push].target` | `garmin` (seule destination d'entraînements). |
| `[health].morning_check` | `full` (HRV + FC repos + sommeil) · `minimal` · `off`. |
| `[health].cycle_tracking` | `off` (défaut, aucune mention) · `ow` · `manual` — opt-in strict. |
| `[glucose].*` | Glycémie Nightscout (lecture seule, opt-in) : plage cible, seuils de départ avant séance. |
| `[load].*` | Constantes de condition (42 j) et de fatigue (7 j). |
| `[guardrails].*` | Seuils et sévérités R1…R7. |
| `[weight_loss].*` | Déficit par défaut, plancher d'énergie disponible, protéines. |

## Agents (`agents/`)

| Agent | Rôle |
|---|---|
| `coach-route` | Vélo de route : blocs, sorties longues, cyclosportives, montagne ; analyse ; push Garmin. |
| `coach-cx` | Cyclo-cross : départs, relances, technique, course 40-60 min, saison sept.-févr. |
| `coach-poids` | Perte de poids sûre, compatible avec l'entraînement ; tendance de poids ; protège les séances clés. |
| `medical` | Bilan matinal (HRV, FC repos, sommeil), verdict 🟢🟡🔴, douleurs, RED-S. Gatekeeper. |
| `nutritionist` | Macros, ravitaillement sur le vélo, énergie disponible, plan de course. |

Délégation via l'outil `task`, uniquement vers `[agents].enabled`. Prompt de tâche en anglais + « Respond in
<langue des documents> » si la sortie est destinée à l'athlète. Chaque agent embarque les règles communes.

## Carte des dossiers

| Dossier | Contenu | Convention |
|---|---|---|
| `activities/` | Séances | `AAAA-MM-JJ_<route\|cx\|strength\|other>.md` |
| `medical/` | Sommeil, HRV, FC repos, verdict, douleurs, poids, météo | `AAAA-MM-JJ_health.md`, `_meteo.md` |
| `nutrition/` | Apports et déficit | `AAAA-MM-JJ_nutrition.md` |
| `planning/` | Profil, objectif, semaines, décisions | `Athlete_Profile.md`, `active_objective.md`, `Semaine_<lundi>.md`, `AAAA-MM-JJ_decision_<slug>.md` |
| `rapports/` | Synthèses (coachs, `coach-poids`) | `AAAA-MM-JJ_rapport.md`, `_poids.md` |
| `resources/` | Base de connaissances perso (gitignoré) | catalogues produits, etc. |

Ces dossiers sont personnels et **gitignorés**.

## Contrat de données

Tout fichier de `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/` s'ouvre par un bloc
```` ```arc ```` de JSON (skill `workspace-data-contract`) : clés en anglais, unités SI, mesure absente = clé
omise. Valider : `python3 scripts/arc_contract.py --validate <fichier>`.

## Scripts (`scripts/`, stdlib Python ≥ 3.9)

| Script | Rôle |
|---|---|
| `arc_ow.py` | Normalise Open Wearables : séances dédoublonnées, sommeil, timeseries, résumé quotidien, FC d'une séance. |
| `arc_cycling.py` | Zones de puissance et FC, charge d'une séance (dont depuis la série de FC), condition / fatigue / forme. |
| `arc_glucose.py` | Contrôle glycémique avant séance, analyse pendant/après, bilan du jour (Nightscout). |
| `arc_override.py` | Analyse des overrides Loop et propositions bornées (lecture seule, rien n'est appliqué). |
| `arc_sync.py` | Rattrapage d'historique Open Wearables → `activities/` (charge depuis la puissance, sinon la FC) et `medical/` (bilans sans verdict). Essai à blanc d'abord. |
| `arc_weight.py` | Tendance de poids, plan de perte, ravitaillement sur le vélo, énergie disponible, BMR. |
| `arc_guardrails.py` | Garde-fous R1…R7 avant d'écrire / pousser une semaine. |
| `arc_workout.py` | Construit le DTO Garmin d'une séance vélo (gabarits route et CX). |
| `arc_contract.py` | Valide les blocs `arc`. |
| `coach_config.py` · `coach_doctor.py` | Configuration · diagnostic. |
| `arc_serve.py` · `dashboard.sh` | **Tableau de bord local** en lecture seule (`./scripts/dashboard.sh` → http://127.0.0.1:8765/) : forme, plan, courses, séances, santé et glycémie déjà persistées. 127.0.0.1 uniquement, CSP stricte. Même identité visuelle que le tableau de bord d'origine (sapin / citron vert, Sora / Inter) ; seule ressource externe : les polices Google Fonts, désactivables par `[dashboard].web_fonts = false`. |
| `arc_files_api.py` | API de fichiers (lecture / écriture validée, atomique, commitée, annulable) : socle des outils MCP. |
| `arc_mcp.py` · `arc_coach_server.py` | **Serveur MCP** (bibliothèque standard, ≈ 27 Mo) qui expose skills, outils déterministes, fichiers et ingestion à Claude mobile/distant ; un seul processus avec le site, sur deux ports. Testé avec le client MCP officiel. Voir `deploy/freebox/README.md`. |
| `daily-sync.sh` | Synchronisation headless (cron). |

Vocabulaire de charge **générique** : *charge*, *condition* (42 j), *fatigue* (7 j), *forme*. Jamais les
sigles déposés TSS / CTL / ATL / TSB.

## Garde-fous

R1 rampe de condition · R2 saut de charge hebdo · R3 jours durs consécutifs · R4 forme plancher · R5 qualité
après verdict rouge (**block**) · R6 vitesse de perte de poids · R7 déficit un jour de séance clé. Les repères
viennent de la littérature mais le seuil exact de blessure ou de surentraînement n'est pas établi : ils
avertissent, ils ne diagnostiquent pas. Voir `config/workspace.toml`.

## Skills (`skills/`)

`workspace-data-contract` · `openwearables-sync` · `garmin-workout-scheduling` · `daily-sync` ·
`nightscout-glucose` · `loop-overrides` (`/override`) · `coach-setup` · `coach-doctor` · `weather-forecast` · commandes courtes `/today`, `/week`, `/log`.

## Premier démarrage

Tant que `config/workspace.user.toml` n'a pas de profil ni `[coaching]`, proposer `/coach-setup` en une ligne,
une seule fois par session ; jamais depuis `/daily-sync`, `/today`, `/week`.
