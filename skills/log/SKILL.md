---
name: log
description: Saisie libre en une phrase (/log) — ravitaillement, boissons, RPE, douleur, poids, repas — « 2 gels + 700 ml, RPE 7, genou gauche 3/10, 78,4 kg ». Extrait les entités, calcule avec scripts/arc_weight.py, écrit dans les bons fichiers au contrat sans jamais inventer une valeur.
---

# /log

Le modèle **extrait** ; les scripts **calculent**. Jamais l'inverse.

| Entité | Où l'écrire |
|:---|:---|
| ravitaillement / boisson pendant une sortie (`carbs_g`, `fluid_intake_ml`) | `activities/` du jour |
| RPE (1-10) | `activities/` du jour (`rpe`) puis recalcule `load` (`arc_cycling.py session`) si aucune FC/puissance |
| douleur (zone + score /10) | `medical/AAAA-MM-JJ_health.md` → `pain` (≥ 7/10 : recommander une consultation) |
| pesée | `medical/` (`weight_kg`) — compte dans la tendance, jamais une décision isolée |
| repas / apports | `nutrition/AAAA-MM-JJ_nutrition.md` |
| phase du cycle déclarée | `cycle_phase`/`cycle_day` — **seulement si** `[health].cycle_tracking` ≠ `off` |

Règles : un produit inconnu ou ambigu → demande l'étiquette, **jamais** de valeur inventée (catalogue :
`resources/nutrition/catalogue-produits-*.md`). Fusion idempotente : relire le fichier du jour, mettre à
jour les clés, ne pas dupliquer. Un seul agent applique TOUTE la fusion d'un message (`nutritionist` s'il
est joignable, sinon le coach). Valide chaque fichier avec `arc_contract.py --validate`.
Aucune activité du jour ? Dis-le et demande de quelle séance il s'agit.
