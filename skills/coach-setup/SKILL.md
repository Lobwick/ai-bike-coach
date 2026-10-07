---
name: coach-setup
description: Premier démarrage (/coach-setup) — entretien pour configurer disciplines, style de coaching, bilan matinal et profil de l'athlète (FTP, LTHR, poids, objectifs), puis écriture de config/workspace.user.toml, planning/Athlete_Profile.md et planning/active_objective.md. Charger quand l'utilisateur lance /coach-setup ou change sa façon de s'entraîner.
---

# /coach-setup

Entretien conversationnel, **jamais deux fois proposé dans une session**, jamais imposé. Ne remplace aucune
réponse existante sans l'accord de l'athlète.

## Questions (une à la fois, saute celles dont la réponse est connue)
1. **Disciplines** : route, cyclo-cross, perte de poids (une ou plusieurs) → `[sport].disciplines`, et
   `[agents].enabled` en conséquence (`coach-route`, `coach-cx`, `coach-poids`, + `medical`, `nutritionist`).
2. **Style** : `bienveillant` / `exigeant` / `factuel` / `pedagogue`, intensité, verbosité → `[coaching]`.
3. **Bilan matinal** : `full` / `minimal` / `off` → `[health].morning_check`.
4. **Open Wearables** : appelle `get_users`, écris l'UUID dans `[data].ow_user_id`. Liste les sources qui
   remontent (Garmin, Whoop, Apple, Strava…) pour fixer `source_priority`.
5. **Profil** : FTP (et date/méthode du dernier test), LTHR, FC max/repos, poids, taille, année de naissance,
   sexe (`m`/`f`, pour les équations — optionnel), disponibilités, matériel (capteur de puissance ?), blessures.
   **Rien d'inventé** : une réponse « je ne sais pas » reste absente (le coach propose un test).
6. **Objectif** : épreuve(s), date, discipline, priorité A/B/C ; objectif de poids (cible + date) le cas échéant.
7. **Diabète / glycémie** : pose la question sans présumer ; si l'athlète a un diabète (ex. type 1 sous Loop) ou suit sa
   glycémie en continu : `[glucose].enabled = true`, plage cible, et `[weight_loss].medical_clearance_required = true`
   (`medical_clearance_confirmed = false` tant que son médecin n'a pas validé un déficit). Note la condition dans la
   section santé du profil. Vérifie que le MCP Nightscout répond (`server_status`, `get_current_glucose`) — lecture seule.
8. **Cycle menstruel** : seulement si pertinent, et jamais présumé → `[health].cycle_tracking`.

## Écriture
- `config/workspace.user.toml` (jamais le fichier versionné).
- `planning/Athlete_Profile.md` depuis `templates/Athlete_Profile.template.md` : renseigne le bloc `arc`
  (`type: "athlete_profile"`), garde les titres des sections.
- `planning/active_objective.md` depuis le gabarit (bloc `objective`).
- Valide : `python3 scripts/arc_contract.py --validate planning/Athlete_Profile.md planning/active_objective.md`
  et `python3 scripts/coach_doctor.py`.
Relancer la commande est sans effet destructif.
