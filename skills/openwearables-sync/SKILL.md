---
name: openwearables-sync
description: Récupération des données via le MCP Open Wearables (séances, sommeil, HRV, FC de repos, poids) sans gonfler le contexte — dédoublonnage des sources, fenêtres de dates minimales, persistance immédiate en Markdown. À charger dès qu'un agent doit lire des données d'activité ou de santé.
---

# Synchronisation Open Wearables

Open Wearables agrège Garmin, Whoop, Apple Santé, Strava… en lecture seule. **Seule source de lecture du
projet.** Garmin n'est utilisé que pour pousser des séances (skill `garmin-workout-scheduling`).

## Règles
1. **Utilisateur** : `[data].ow_user_id` ; vide → `get_users` (un seul utilisateur = lui).
2. **Fenêtre minimale** : ne demande que les dates dont le fichier n'existe pas encore
   (`activities/`, `medical/`). Une plage de quelques jours, jamais « toute l'histoire » d'un coup
   (premier remplissage : par blocs de 14 jours).
3. **Passer par le dédoublonneur** — `get_workout_events` → `python3 scripts/arc_ow.py workouts`
   (la réponse JSON brute en stdin ou `--file`). Il fusionne les copies de la même séance
   (Apple/Strava/Whoop/Garmin), complète les champs manquants, supprime l'allure inutile à vélo,
   conserve les calories de chaque source, et marque les `envelope` (bloc qui en recouvre plusieurs)
   `counted: false`.
4. **Timeseries** (`resting_heart_rate`, `heart_rate_variability_rmssd`, `weight`, `body_fat_percentage`) :
   résolution `1hour`, plage courte ; `arc_ow.py daily`. Sommeil : `arc_ow.py sleep`.
5. **Discipline du chat** : jamais de JSON brut dans la conversation ; résume en une ligne par séance.
6. **Persister immédiatement** après chaque récupération : une séance = `activities/AAAA-MM-JJ_<discipline>.md`
   (bloc `activity`, `ow_ids`, `sources`), santé du jour = `medical/AAAA-MM-JJ_health.md`.
   Plusieurs séances le même jour : un fichier par séance (`_route`, `_route_2`, `_cx`…).
7. **Discipline** d'une séance Open Wearables (`type: cycling`) : `route` par défaut ; `cx` si l'athlète le
   dit, si l'objectif actif est du cyclo-cross et que c'est un jour de course ou de séance technique, ou si la
   séance planifiée du jour le précise. En cas de doute en interactif, demande ; en headless garde `route`
   et note l'incertitude dans le texte. `type: generic`/`walking` etc. → `other`, sans charge.
8. **Charge** : `arc_cycling.py session` (puissance > FC > RPE). Pas de méthode possible → pas de `load`,
   RPE demandé en interactif.
9. **Limites dites, jamais comblées** : pas de puissance/NP, pas de FC de récupération, pas de tours.
   Une source peut manquer un jour (capteur non porté) : « indisponible », pas une anomalie.
10. **Poids / masse grasse** : l'ordre des sources suit `[data].source_priority` ; ne retiens que la
    tendance pour décider (`arc_weight.py trend`).
11. **Glycémie** : elle ne vient PAS d'Open Wearables mais du MCP Nightscout (skill `nightscout-glucose`, lecture seule,
    si `[glucose].enabled`). Les deux se recoupent par l'heure de la séance (début/fin déjà dédoublonnés).
