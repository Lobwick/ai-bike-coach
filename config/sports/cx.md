# Profil sportif — `cx` (cyclo-cross)

Chargé par `coach-cx`.

## Format de course
40 à 60 min selon la catégorie, circuit 2,5-3,5 km, 6-8 tours. Départ de 10-15 s à fond, relances
répétées à sortie de virage / obstacle (≥ 150 % FTP, 5-15 s), portages et franchissements à pied, boue,
sable, bosse. Saison : septembre → février (pré-saison juillet-août).

## Vocabulaire des séances (`intensity`)
| id | Séance | Contenu type |
|:---|:---|:---|
| `recovery` | Récupération | 45-60 min très facile, cadence souple |
| `endurance` | Endurance + technique | 1 h 30 Z2 avec 20 min de technique (virages, remontées) |
| `tempo` | Tempo | 2 × 15 min 76-90 % FTP |
| `threshold` | Seuil | 3 × 10 min 95-105 % FTP |
| `vo2max` | Relances VO2max | 30/30 ou 40/20 × 8-12, 3 séries, 100-120 % |
| `anaerobic` | Départs / relances | 6 × 15 s départ + récup complète ; 8 × 20 s à ≥ 150 % FTP |
| `race` | Course | 40-60 min, facteur 1,0 |
| `strength` | Renforcement | gainage, force bas du corps, mobilité hanches/dos |

Gabarits Garmin : `cx_race_sim` (relances au rythme d'un tour), `cx_starts` (départs), `cx_opener` (ouverture à J-2 : 3 départs + 3 relances), `recovery` (dégourdissage la veille d'une course), plus les gabarits
route (`threshold`, `vo2max`, `endurance`). Le sport Garmin reste `cycling`.

## Matériel par défaut à lister pour chaque séance / course
Vélo + vélo de secours, jeux de roues (boue/sec), pression de pneus à décider selon le terrain,
chaussures à crampons, tenue pluie/froid, protections, outil de dépannage, lavage après course,
nourriture (peu pendant ≤ 60 min). Reconnaissance du circuit à pied avant la course.

## Règles de planification
- Une seule séance dure en semaine de course. 48 h sans qualité après une course.
- Course dimanche : ouverture jeudi (2-3 relances courtes + 1 départ), repos ou facile vendredi,
  reconnaissance samedi.
- Pas de déficit calorique en semaine de course ni dans les 48 h avant.

## Unité de charge
*Charge* = 100 pour 1 h au seuil. Une course de 45 min vaut en général 75-85 (facteur 1,0).
Mesure d'une course : FC moyenne/max + RPE, jamais la seule puissance moyenne.
