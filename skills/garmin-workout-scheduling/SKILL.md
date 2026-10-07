---
name: garmin-workout-scheduling
description: Pousser des entraînements vélo sur le calendrier Garmin Connect via les outils d'ÉCRITURE du serveur garmin (schedule_workouts, schedule_week, upload_workout). Schéma DTO exact, cibles de puissance/FC, idempotence, vérification après push. Garmin ne sert qu'à pousser — jamais à lire les données.
---

# Pousser un entraînement vélo sur Garmin

**Rôle de Garmin dans ce projet : destination des séances uniquement.** Les données se lisent dans
Open Wearables (`openwearables-sync`). Seuls ces outils `garmin` sont utilisés :
`schedule_workouts`, `schedule_week`, `upload_workout`, `get_scheduled_workouts`, `get_workout_by_id`,
`get_workouts`, `unschedule_workout(s)`, `delete_workout`, `create_strength_workout`.

## Conditions du push (toutes obligatoires)
1. Garde-fous passés sur la semaine : `python3 scripts/arc_guardrails.py check --week <fichier|->`
   (un `block` n'empêche pas les autres séances ; voir les règles des agents).
2. **« Oui » explicite** de l'athlète dans la conversation, pour ce push. Jamais généralisé.
3. **Jamais en headless** (`/daily-sync`).

## Construire le `workout_data`
Ne l'écris pas à la main : `python3 scripts/arc_workout.py template <nom> --duration-s N`
(`endurance`, `sweet_spot`, `threshold`, `vo2max`, `cx_race_sim`, `cx_starts`) lit le profil
(`ftp_w`, sinon `lthr_bpm`) et sort `{"workout_data": {...}}`. Séance libre :
`arc_workout.py build --spec spec.json` (voir l'en-tête du script). Contrôle : `arc_workout.py validate`.
- **Cible de puissance** (`power.zone`, `targetValueOne/Two` en **watts**, bas puis haut) si le FTP est connu ;
  sinon cible FC (`heart.rate.zone`, bpm) si le LTHR l'est ; sinon `no.target` avec consigne en RPE.
  Jamais une valeur inventée.
- Clés exactes : `workoutSegments` / `workoutSteps` / `endConditionValue`. `steps` ou `conditionValue` =
  erreur 400. Boucles : `RepeatGroupDTO` + `numberOfIterations` + endCondition `iterations` (id 7).
- Sport : `{"sportTypeId": 2, "sportTypeKey": "cycling"}` (route ET cyclo-cross).
- Renforcement : `{"sportTypeId": 5, "sportTypeKey": "strength_training"}` avec exercices, séries,
  répétitions, charge et repos détaillés (`create_strength_workout` ou DTO structuré), jamais « Renfo 40 min ».

### Tables
| stepType | id | key | | endCondition | id | key |
|---|---|---|---|---|---|---|
| Échauffement | 1 | warmup | | Bouton tour | 1 | lap.button |
| Retour au calme | 2 | cooldown | | Temps (s) | 2 | time |
| Effort | 3 | interval | | Distance (m) | 3 | distance |
| Récupération | 4 | recovery | | Itérations | 7 | iterations |
| Repos | 5 | rest | | Répétitions | 10 | reps |

| targetType | id | key | statut |
|---|---|---|---|
| Aucune | 1 | no.target | vérifié |
| Puissance | 2 | power.zone | **à vérifier au 1er push** |
| Cadence | 3 | cadence.zone | **à vérifier au 1er push** |
| FC | 4 | heart.rate.zone | vérifié |

⚠ Après le **premier** push avec une cible de puissance : `get_workout_by_id` puis contrôle visuel des
watts dans Garmin Connect avant de faire confiance au mécanisme.

## Idempotence — critique
- `workout_data` en ligne n'est **pas** idempotent : chaque appel crée un NOUVEL entraînement ; re-pousser
  une date laisse l'ancien à côté.
- **Avant de pousser** une date : `get_scheduled_workouts(start_date, end_date)`. Même séance → réutilise
  son `workout_id` ; séance modifiée → `unschedule_workout`/`delete_workout` de l'ancien, puis pousse le neuf.

## Procédure
1. Lis la semaine (`planning/Semaine_<lundi>.md`). 2. Garde-fous. 3. « Oui ». 4. `get_scheduled_workouts`
de la semaine (doublons, entrées périmées `completed=false`). 5. Gabarit/DTO par séance. 6. Pousse par lots de
**3-5 séances** (un lot de 8 a échoué en JSON). 7. **Vérifie** : `get_scheduled_workouts` (date, durée, nom,
aucun doublon) et `get_workout_by_id` pour le détail. 8. Écris `garmin_workout_id` dans la séance du fichier
semaine et revalide.
- Timeout MCP : ne présume pas un échec — revérifie avec `get_scheduled_workouts` avant de re-pousser.
- Course (jour J) : ne se pousse pas comme un entraînement ; note-la dans la semaine.
