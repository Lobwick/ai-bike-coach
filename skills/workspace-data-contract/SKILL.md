---
name: workspace-data-contract
description: Contrat de données des fichiers persistés — chaque fichier de activities/, medical/, nutrition/, planning/ ou rapports/ s'ouvre par un bloc ```arc de JSON typé, unités SI, validé par scripts/arc_contract.py. Charger AVANT d'écrire ou réécrire un de ces fichiers.
---

# Contrat de données

Chaque fichier écrit par un agent s'ouvre, **sous son titre `# …`**, par UN seul bloc :

````
# Sortie longue — 2026-10-05

```arc
{ "type": "activity", "date": "2026-10-05", "discipline": "route", "duration_s": 6432 }
```

Texte libre en français ici…
````

Règles : clés en anglais · unités SI (m, s, bpm, W, kg, kcal) quelle que soit `[athlete].units` ·
**mesure absente = clé omise** (jamais `0`, jamais `null`) · le texte libre reste sous le bloc.
Valider après écriture : `python3 scripts/arc_contract.py --validate <fichier>` et corriger toute
erreur nommée. Exceptions : aucune — le profil et l'objectif portent eux aussi un bloc (`athlete_profile`, `objective`).

## Types

| `type` | Fichier | Obligatoires | Principales clés optionnelles |
|:---|:---|:---|:---|
| `activity` | `activities/AAAA-MM-JJ_<route|cx|strength|other>.md` | `date`, `discipline` (`route`/`cx`/`strength`/`poids`/`other`), `duration_s` | `distance_m`, `elevation_gain_m`, `avg_hr_bpm`, `max_hr_bpm`, `avg_power_w`, `np_w`, `rpe`, `load`, `load_method` (`power`/`hr`/`trimp`/`rpe`), `intensity`, `race`, `calories_kcal`, `carbs_g`, `fluid_intake_ml`, `weight_pre_kg`, `weight_post_kg`, `ow_ids`, `sources`, `gear_ids` |
| `health` | `medical/AAAA-MM-JJ_health.md` | `date` | `resting_hr_bpm`, `hrv_rmssd_ms`, `sleep_min`, `verdict` (`green`/`amber`/`red`), `verdict_reason`, `pain` (`[{"location","score"}]`), `weight_kg`, `body_fat_pct`, `cycle_phase`, `cycle_day` |
| `nutrition` | `nutrition/AAAA-MM-JJ_nutrition.md` | `date` | `intake_kcal`, `protein_g`, `carbs_g`, `fat_g`, `deficit_kcal`, `burned_kcal`, `energy_availability` |
| `week` | `planning/Semaine_<lundi>.md` | `week_start` (un LUNDI), `sessions[]` | `phase`, `focus`, `deficit_kcal_by_date` |
| `decision` | `planning/AAAA-MM-JJ_decision_<slug>.md` | `date`, `trigger`, `outcome` (`proposed`/`applied`/`superseded`/`declined`) | `rule_ids`, `before`, `after`, `session_ref`, `supersedes`, `inputs` |
| `report` | `rapports/AAAA-MM-JJ_rapport.md` / `_poids.md` | `date`, `period_start`, `period_end` | `report_type`, `load`, `weight` |
| `athlete_profile` | `planning/Athlete_Profile.md` | — | `ftp_w`, `lthr_bpm`, `hr_max_bpm`, `hr_rest_bpm`, `weight_kg`, `target_weight_kg`, `height_cm`, `birth_year`, `sex`, `body_fat_pct`, `disciplines`, `available_days` |
| `objective` | `planning/active_objective.md` | `name`, `date`, `discipline` | `kind`, `priority` (`A`/`B`/`C`), `target_weight_kg`, `target_date` |

### Séance d'une semaine (`sessions[i]`)
`date` (dans la semaine), `discipline`, `title` obligatoires ; `intensity` (`rest`, `recovery`, `endurance`,
`tempo`, `threshold`, `vo2max`, `anaerobic`, `race`, `strength`), `duration_s`, `key` (booléen, séance clé),
`planned_load`, `garmin_workout_id` après un push.

### Décision — protocole
Un garde-fou, le bilan matinal ou un avis médical modifie/annule une séance → écrire d'abord la semaine
corrigée, PUIS la décision qui la référence, PUIS valider les deux. Une décision publiée ne se réédite pas :
remplace-la par une nouvelle (`outcome: "applied"`, `supersedes: <chemin>`) et passe l'ancienne à `superseded`.

## Charge d'une séance
`load` + `load_method` viennent de `python3 scripts/arc_cycling.py session …`. Ne calcule rien à la main.
