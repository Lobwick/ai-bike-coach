# Profil sportif — `route` (vélo de route)

Chargé par `coach-route` (et lu par les autres agents quand `route` est dans `[sport].disciplines`).

## Vocabulaire des séances (`intensity`)
| id | Séance | Zone puissance | Zone FC (% seuil) | RPE |
|:---|:---|:---|:---|:---|
| `recovery` | Récupération active | Z1 (< 55 % FTP) | < 81 % | 1-2 |
| `endurance` | Endurance de base | Z2 (56-75 %) | 81-89 % | 3-4 |
| `tempo` | Tempo | Z3 (76-90 %) | 90-93 % | 5-6 |
| `threshold` | Seuil / sweet spot haut | Z4 (91-105 %) | 94-99 % | 7-8 |
| `vo2max` | VO2max | Z5 (106-120 %) | 100-106 % | 9 |
| `anaerobic` | Capacité anaérobie / sprints | Z6-Z7 (> 120 %) | — | 9-10 |
| `race` | Cyclosportive / course | selon l'objectif | — | — |
| `strength` | Renforcement | — | — | — |

Gabarits Garmin disponibles : `arc_workout.py templates` (`endurance`, `sweet_spot`, `threshold`, `vo2max`).

## Unité de charge
*Charge* = 100 pour 1 h au seuil (FTP ou LTHR). Voir `scripts/arc_cycling.py`.

## Matériel par défaut à lister pour chaque sortie
Casque, lunettes, 2 bidons (ou 1 + poche), nécessaire de crevaison (chambre, démonte-pneus, pompe/CO₂),
nourriture selon `arc_weight.py fuel`, veste coupe-vent selon la météo, éclairage si la sortie finit
au crépuscule. Montagne : coupe-vent + manchettes pour la descente.

## Métriques de suivi à demander quand elles manquent
FTP et date du dernier test · poids · FC max / repos / seuil · disponibilités hebdo · objectif (date,
dénivelé, durée).
