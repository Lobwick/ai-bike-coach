---
name: today
description: Commande courte /today — séance du jour (fichier semaine de planning/), bilan matinal au niveau [health].morning_check, météo si sortie extérieure. Verdict en une ligne d'abord. N'écrit aucun plan et ne pousse rien sur Garmin.
---

# /today

Question factuelle : réponds court, **ne propose pas `/coach-setup`**.
1. Lis `planning/Semaine_<lundi>.md` : séance du jour (ou « rien de prévu »).
2. Bilan matinal selon `[health].morning_check` (skill `openwearables-sync`, dates manquantes seulement ;
   persiste `medical/AAAA-MM-JJ_health.md` comme les règles de fraîcheur l'exigent).
3. Si sortie extérieure : météo + créneau (`weather-forecast`).
4. Ouvre par **UNE ligne de verdict** : « 🟢 Séance maintenue : seuil 3×10 — départ 12 h » ; ensuite seulement
   le détail (cibles, durée, matériel). Un `red` ou un `block` ne s'assouplit pas : propose une alternative.
Ne crée ni semaine, ni décision, ni push.
