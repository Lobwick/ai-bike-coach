---
name: openwearables-sync
description: Récupération des données via le MCP Open Wearables (séances, FC détaillée, sommeil, HRV, FC de repos, respiration, SpO2, poids, résumé quotidien) sans gonfler le contexte — quel outil pour quelle donnée, fenêtres minimales, valeurs nulles = absentes, persistance immédiate en Markdown. À charger dès qu'un agent doit lire des données d'activité ou de santé.
---

# Synchronisation Open Wearables

Open Wearables agrège Garmin, Whoop, Apple Santé, Strava… en lecture seule. **Seule source de lecture du projet**
(avec Nightscout pour la glycémie, skill `nightscout-glucose`). Garmin n'est utilisé que pour pousser des séances
(skill `garmin-workout-scheduling`).

## Quel outil pour quelle donnée
| Besoin | Outil MCP | Passage par `scripts/arc_ow.py` | Écrit dans |
|:---|:---|:---|:---|
| Séances (durée, distance, D+, FC moy./max, calories) | `get_workout_events` | `workouts` | `activities/` |
| FC détaillée d'UNE séance (charge, zones, dérive) | `get_timeseries(types=["heart_rate"], resolution="5min")` sur la fenêtre de la séance | `hr` → `arc_cycling.py hr-load` | `activities/` (`load`, `time_in_zone_min`…) |
| Sommeil (durée, début/fin ; phases si la source en fournit) | `get_sleep_summary` | `sleep` | `medical/` (`sleep_min`) |
| FC de repos, HRV (rmssd/sdnn), fréquence respiratoire, SpO₂, poids, masse grasse | `get_timeseries` (`1hour`) | `daily` | `medical/` |
| Dépense du jour, pas, FC du jour, minutes d'intensité | `get_activity_summary` | `activity` | `medical/` ou `nutrition/` (`total_kcal`, `burned_kcal`) |
| Cycle menstruel (opt-in) | `get_menstrual_cycles` | — | `medical/` |
Le préfixe d'outil dépend du client (ex. `mcp__claude_ai_Open_wearables_3__…`).

## Règles
1. **Utilisateur** : `[data].ow_user_id` ; vide → `get_users` (un seul utilisateur = lui).
2. **Fenêtre minimale** : seulement les dates dont le fichier n'existe pas (`activities/`, `medical/`). Quelques jours
   à la fois ; premier remplissage par blocs de 14 jours. Garde les réponses lourdes hors de la conversation : sauve-les
   dans un fichier temporaire (scratchpad) et traite-les avec les scripts.
3. **Doublons** : devenus rares, pas nuls (ex. deux enregistrements Apple pour une même sortie, deux échantillons de FC au
   même instant). **Passe toujours** les séances par `arc_ow.py workouts` : sans doublon, il ne change rien. Une
   `envelope` (`counted: false`) est un bloc qui en recouvre plusieurs : listée, jamais additionnée.
4. **Valeur `0` = absente** pour l'énergie, les pas et la distance du résumé quotidien (jour non synchronisé) : le script
   l'omet et marque `energy_missing`. Une dépense absente ne se remplace pas par une estimation inventée ; dis-le.
5. **Énergie** : n'additionne JAMAIS les séries horaires `active_energy`/`basal_energy` (valeurs cumulées à la
   synchronisation, doublons : 3 755 kcal dans un seul créneau). Total du jour = `total_kcal` de `get_activity_summary` quand
   il est présent ; calories d'une séance = `calories_by_source` (jamais sommées, source indiquée).
6. **Charge d'une séance** (par ordre de précédence, méthode toujours écrite) : puissance déclarée > **série de FC**
   (`arc_cycling.py hr-load --timeseries ts.json --start … --end …`) > FC moyenne (`session --avg-hr`) > RPE. La série
   exige FC repos + FC max au profil. Les valeurs d'une série sont des moyennes par intervalle : le pic réel est
   plus haut, préfère `max_heart_rate_bpm` de la séance quand elle existe. La dérive de FC n'a de sens que sur un effort régulier.
7. **Persister immédiatement** après chaque récupération : une séance = `activities/AAAA-MM-JJ_<discipline>.md` (bloc
   `activity`, `ow_ids`, `sources`) ; santé du jour = `medical/AAAA-MM-JJ_health.md`. Plusieurs séances le même jour : un
   fichier chacune (`_route`, `_route_2`, `_cx`…). Jamais de JSON brut dans le chat : une ligne par séance.
8. **Discipline** d'une séance (`type: cycling`) : `route` par défaut ; `cx` si l'athlète le dit, si c'est un jour de course ou
   de séance technique de l'objectif actif, ou si la séance planifiée du jour le précise. Doute en interactif : demande ; en
   headless : `route` et note l'incertitude. `generic`, `walking`… → `other`, sans charge.
9. **Limites dites, jamais comblées** : pas de puissance/NP (sauf déclarée), pas de FC de récupération, pas de tours, pas de
   phases de sommeil selon la source. Une nuit sans HRV (capteur non porté) = « indisponible », pas une anomalie. Une
   mesure absente ne devient jamais 0.
10. **Bilan matinal** (selon `[health].morning_check`) : sommeil, FC de repos (minimum plausible du jour), HRV ; en complément
    informatif la fréquence respiratoire et la SpO₂ du matin, comparées à la base PERSONNELLE de l'athlète (jamais à une norme
    ni à un seuil absolu) — un écart durable les deux ensemble avec FC de repos haute peut signaler une maladie en cours :
    alléger et, si cela persiste ou s'accompagne de symptômes, recommander un avis médical. Pas de diagnostic.
11. **Poids / masse grasse** : source la mieux classée de `[data].source_priority` ; ne décider que sur la tendance
    (`arc_weight.py trend`), une pesée isolée ne déclenche rien ; masse grasse de balance = estimation grossière.
12. **Glycémie** : pas d'Open Wearables ; MCP Nightscout, lecture seule (`nightscout-glucose`).
