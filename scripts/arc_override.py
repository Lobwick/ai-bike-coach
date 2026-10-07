#!/usr/bin/env python3
"""Overrides Loop (via Nightscout) : ANALYSE et PROPOSITIONS — jamais d'écriture, jamais de dose.

    python3 scripts/arc_override.py presets     --profile profile.json
    python3 scripts/arc_override.py activations --treatments t.json [--days 30]
    python3 scripts/arc_override.py analyze     --sessions s.json --activations a.json --presets p.json

Pourquoi aucune écriture : les préréglages (`overridePresets`) sont DÉFINIS dans l'app Loop sur le
téléphone ; Nightscout n'en reçoit qu'une copie (document de profil écrit par Loop, `enteredBy: Loop`).
Modifier cette copie ne change rien côté Loop, sera écrasé au prochain envoi, et le même document
contient basales, sensibilité et ratios glucides. Créer ou modifier un préréglage se fait donc dans
Loop, par l'athlète, idéalement après avis de son équipe de diabétologie. Ce script produit des
HYPOTHÈSES à discuter, bornées par des pas minuscules (± `STEP_SCALE`, ± `STEP_TARGET` mg/dL), appuyées
sur les séances réelles de l'athlète (≥ `MIN_SESSIONS` par préréglage), jamais sur une norme.

`presets` ne sort QUE nom, symbole, facteur d'insuline, plage cible, durée : jamais le jeton
d'appareil, ni basales, ni sensibilité, ni ratios, ni limites de dosage.

Entrées `analyze` :
- sessions : liste de sorties de `arc_glucose.py session` enrichies de `start`/`end` (ISO) ;
- activations : sortie de `activations` ; presets : sortie de `presets`.
Ce n'est pas un avis médical.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STEP_SCALE = 0.05          # pas maximal sur le facteur d'insuline proposé
STEP_TARGET = 10           # pas maximal sur la plage cible (mg/dL)
MIN_SESSIONS = 3           # séances minimum par préréglage pour une proposition chiffrée
SCALE_BOUNDS = (0.05, 1.0)
DEDUP_MIN = 3              # deux activations du même préréglage à < 3 min = la même
CAP_H = 8                  # durée plafond d'un override sans fin explicite
LOW, HIGH_ALERT = 70, 250


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def presets(doc):
    docs = doc.get("result", doc) if isinstance(doc, dict) else doc
    if isinstance(docs, dict):
        docs = [docs]
    for d in docs or []:
        ps = (d.get("loopSettings") or {}).get("overridePresets")
        if ps is not None:
            return {"presets": [
                {"name": p.get("name"), "symbol": p.get("symbol"),
                 "insulin_scale": p.get("insulinNeedsScaleFactor"),
                 "target_range_mgdl": p.get("targetRange"),
                 "duration_min": round(p["duration"] / 60) if p.get("duration") else None}
                for p in ps],
                "note": "copie Nightscout ; la référence est l'app Loop"}
    return {"error": "aucun préréglage trouvé dans le profil Nightscout"}


def _name(reason, known):
    r = (reason or "").lower()
    for n in known:
        if n and n.lower() in r:
            return n
    toks = [t for t in r.replace("️", "").split() if t.isalnum()]
    return toks[-1] if toks else "inconnu"


def activations(doc, known=("sport", "long", "stop"), days=None):
    rows = doc.get("result", doc) if isinstance(doc, dict) else doc
    ev = []
    for t in rows or []:
        et = t.get("eventType", "")
        if et not in ("Temporary Override", "Temporary Override Cancel"):
            continue
        ev.append({"t": _dt(t.get("timestamp") or t["created_at"]), "cancel": et.endswith("Cancel"),
                   "name": None if et.endswith("Cancel") else _name(t.get("reason"), known),
                   "scale": t.get("insulinNeedsScaleFactor"), "range": t.get("correctionRange"),
                   "duration": t.get("duration") or 0, "remote": "remote" in (t.get("enteredBy") or "")})
    ev.sort(key=lambda e: e["t"])
    if days and ev:
        cut = ev[-1]["t"] - timedelta(days=days)
        ev = [e for e in ev if e["t"] >= cut]
    merged = []
    for e in ev:
        if merged and not e["cancel"] and not merged[-1]["cancel"] and merged[-1]["name"] == e["name"] \
                and (e["t"] - merged[-1]["t"]) < timedelta(minutes=DEDUP_MIN):
            merged[-1]["duration"] = max(merged[-1]["duration"], e["duration"])
            continue
        merged.append(e)
    out = []
    for i, e in enumerate(merged):
        if e["cancel"]:
            continue
        end = e["t"] + timedelta(minutes=e["duration"]) if e["duration"] else None
        nxt = next((m["t"] for m in merged[i + 1:]), None)
        capped = False
        if end is None or (nxt and nxt < end):
            end = nxt or e["t"] + timedelta(hours=CAP_H)
            capped = nxt is None
        out.append({"name": e["name"], "start": e["t"].isoformat(), "end": end.isoformat(),
                    "insulin_scale": e["scale"], "target_range_mgdl": e["range"],
                    "remote": e["remote"], **({"end_assumed": True} if capped else {})})
    return {"activations": out}


def _active(acts, s, e):
    """Préréglage actif pendant la séance (le plus long chevauchement) + avance d'activation."""
    best, best_ov = None, 0
    for a in acts:
        a_s, a_e = _dt(a["start"]), _dt(a["end"])
        ov = (min(a_e, e) - max(a_s, s)).total_seconds()
        if ov > best_ov and a["name"] != "stop":
            best, best_ov = a, ov
    if not best:
        return None, None
    return best["name"], round((s - _dt(best["start"])).total_seconds() / 60)


def _step(cur, delta, lo=None, hi=None):
    v = cur + delta
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return round(v, 2)


def analyze(sessions, acts, pres):
    by = {}
    for s in sessions:
        if "error" in s or not s.get("window"):
            continue
        st, en = _dt(s["window"]["start"]), _dt(s["window"]["end"])
        name, lead = _active(acts, st, en)
        by.setdefault(name or "aucun", []).append({**s, "_lead": lead})
    preset_by_name = {p["name"]: p for p in pres}
    groups, proposals = [], []
    for name, ss in sorted(by.items()):
        n = len(ss)
        lows = [x for x in ss if x.get("hypo_events")]
        low_start = [x for x in ss if x.get("glucose_start_mgdl", 999) < 90]
        highs = [x for x in ss if x.get("glucose_max_mgdl", 0) >= HIGH_ALERT]
        leads = sorted(x["_lead"] for x in ss if x["_lead"] is not None)
        g = {"override": name, "sessions": n, "with_hypo": len(lows), "start_below_90": len(low_start),
             "max_ge_250": len(highs)}
        mins = [x["glucose_min_mgdl"] for x in ss if "glucose_min_mgdl" in x]
        if mins:
            g["avg_min_mgdl"] = round(sum(mins) / len(mins))
        if leads:
            g["median_lead_min"] = leads[len(leads) // 2]
        groups.append(g)
        if n < MIN_SESSIONS:
            proposals.append({"override": name, "kind": "insuffisant",
                              "message": f"{n} séance(s) seulement (< {MIN_SESSIONS}) : pas de proposition chiffrée"})
            continue
        cur = preset_by_name.get(name)
        if name == "aucun":
            if lows or low_start:
                base = preset_by_name.get("sport")
                proposals.append({
                    "override": "aucun", "kind": "creer_ou_utiliser", "status": "hypothèse",
                    "evidence": f"{len(lows)} hypoglycémie(s) et {len(low_start)} départ(s) < 90 mg/dL sur {n} séances SANS préréglage",
                    "proposal": "utiliser un préréglage existant ou en créer un pour ce type de séance"
                                + (f" ; point de départ à discuter : copie de « sport » ({base['insulin_scale']}, "
                                   f"{base['target_range_mgdl']})" if base else ""),
                })
            continue
        if not cur or cur.get("insulin_scale") is None:
            continue
        if len(lows) >= 2 or (len(lows) / n) >= 0.34:
            tgt = cur.get("target_range_mgdl")
            p = {"override": name, "kind": "moins_agressif", "status": "hypothèse",
                 "evidence": f"hypoglycémie sur {len(lows)}/{n} séances avec « {name} »",
                 "proposal": {"insulin_scale": {"current": cur["insulin_scale"],
                                                 "candidate": _step(cur["insulin_scale"], -STEP_SCALE, *SCALE_BOUNDS)}}}
            if tgt:
                p["proposal"]["target_range_mgdl"] = {"current": tgt, "candidate": [t + STEP_TARGET for t in tgt]}
            if leads and leads[len(leads) // 2] < 30:
                p["proposal"]["timing"] = (f"activation médiane {leads[len(leads) // 2]} min avant le départ : "
                                           "envisager de l'activer plus tôt (à discuter) avant de toucher aux chiffres")
            proposals.append(p)
        elif len(highs) >= 2 and not lows:
            tgt = cur.get("target_range_mgdl")
            p = {"override": name, "kind": "plus_agressif", "status": "hypothèse",
                 "evidence": f"glycémie ≥ {HIGH_ALERT} mg/dL sur {len(highs)}/{n} séances avec « {name} », sans hypoglycémie "
                             "(effet possible de l'intensité ou de l'adrénaline)",
                 "proposal": {"insulin_scale": {"current": cur["insulin_scale"],
                                                 "candidate": _step(cur["insulin_scale"], +STEP_SCALE, *SCALE_BOUNDS)}}}
            if tgt:
                p["proposal"]["target_range_mgdl"] = {"current": tgt, "candidate": [max(90, t - STEP_TARGET) for t in tgt]}
            proposals.append(p)
        else:
            proposals.append({"override": name, "kind": "aucun_changement",
                              "message": f"« {name} » : rien à proposer sur {n} séances (pas de motif récurrent)"})
    unused = [p["name"] for p in pres if p["name"] not in by and p["name"] != "stop"]
    return {"groups": groups, "proposals": proposals,
            "unused_presets": unused,
            "how_to_apply": "Dans l'app Loop (Réglages → Préréglages d'override), par l'athlète lui-même, "
                            "après avis de son équipe de diabétologie. Aucun changement n'est fait automatiquement.",
            "limits": f"hypothèses bornées à ±{STEP_SCALE} (facteur) et ±{STEP_TARGET} mg/dL (plage), "
                      f"≥ {MIN_SESSIONS} séances par préréglage ; basales, sensibilité, ratios et limites de dosage "
                      "ne sont jamais abordés",
            "disclaimer": "ce n'est pas un avis médical"}


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, a, opt = argv[1], argv[2:], {}
    while a:
        k = a.pop(0)
        if k.startswith("--"):
            opt[k[2:]] = a.pop(0)
    load = lambda p: json.load(open(p, encoding="utf-8"))  # noqa: E731
    if cmd == "presets":
        res = presets(load(opt["profile"]))
    elif cmd == "activations":
        res = activations(load(opt["treatments"]), days=int(opt["days"]) if "days" in opt else None)
    elif cmd == "analyze":
        sess = load(opt["sessions"])
        acts = load(opt["activations"])["activations"]
        pr = load(opt["presets"])
        res = analyze(sess if isinstance(sess, list) else sess["sessions"], acts, pr.get("presets", []))
    else:
        print(__doc__)
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 1 if "error" in res else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
