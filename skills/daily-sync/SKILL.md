---
name: daily-sync
description: Prompt d'orchestration HEADLESS (/daily-sync) lancé par cron via scripts/daily-sync.sh — met à jour séances, sommeil, HRV, FC de repos et poids depuis Open Wearables, écrit le bilan matinal, termine par un bloc ```resume```. Ne pose aucune question, ne pousse rien sur Garmin.
---

# /daily-sync (non interactif)

Aucune question, aucun push Garmin, aucune écriture externe. Si une décision exige l'athlète, écris-la en
`proposed` et arrête-toi.

1. **Config** : `config/workspace.toml` + `.user.toml` ; `[sync].lookback_days` (défaut 2), `[health].morning_check`.
2. **Dates manquantes** : pour chacune des `lookback_days` dernières dates (aujourd'hui inclus), regarde si
   `activities/` et `medical/AAAA-MM-JJ_health.md` existent. Ne récupère que ce qui manque.
3. **Lecture** (skill `openwearables-sync`) : `get_workout_events` → `arc_ow.py workouts` ;
   `get_sleep_summary` → `arc_ow.py sleep` ; `get_timeseries` (FC de repos, HRV, poids) → `arc_ow.py daily`.
   Écris chaque fichier immédiatement ; valide avec `arc_contract.py --validate`.
4. **Charge** : `arc_cycling.py session` par séance (puissance > FC > RPE) ; sans méthode possible, pas de `load`
   — note « RPE manquant » dans le résumé (jamais de question).
5. **Bilan matinal** selon `[health].morning_check` : délègue à `medical` s'il est joignable, sinon applique
   toi-même ses règles ; écris `verdict` dans `medical/AAAA-MM-JJ_health.md`.
6. **Garde-fous** : sur la semaine en cours, `arc_guardrails.py check`. Un `block` → écris une décision
   `proposed`, ne modifie rien.
7. **Poids** (si `poids` actif) : `arc_weight.py trend`, alerte si perte > plafond.
8. **Clôture** — termine par EXACTEMENT un bloc :

````
```resume
Séances : 2 nouvelles (route 1 h 47, cx 0 h 45) · charge 3 j : 212
Forme : −8 (condition 54, fatigue 62) · verdict : 🟡 amber (FC repos +6)
Poids : 78,6 kg (tendance −0,4 kg/sem.)
Alerte : séance seuil de demain proposée en remplacement (R5) — à confirmer
```
````
5 lignes maximum, rien d'inventé : une donnée absente s'écrit « indisponible ».
