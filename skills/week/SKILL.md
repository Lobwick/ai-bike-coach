---
name: week
description: Commande courte /week — état de la semaine en cours (fait / prévu / reste, charge, garde-fous) en tableau. N'écrit aucun plan et ne pousse rien.
---

# /week

1. Lis `planning/Semaine_<lundi>.md` (type `week`) et les `activities/` de la semaine.
2. Tableau : jour · prévu · fait (durée, charge) · statut (✅ fait / ⏳ à venir / ✖ manqué).
3. Totaux : charge faite vs planifiée (`arc_cycling.py load`), forme actuelle, jours durs restants.
4. `arc_guardrails.py check --week <fichier>` : ne cite que les `warn`/`block`, en une phrase chacun.
5. Si `[glucose].enabled` : `calculate_time_in_range` / `get_glucose_stats_batch` sur 7 jours (temps dans la cible, sous 70) — une ligne.
6. Si `poids` est actif : tendance de poids de la semaine (`arc_weight.py trend`), une ligne.
Aucune écriture de plan, aucun push.
