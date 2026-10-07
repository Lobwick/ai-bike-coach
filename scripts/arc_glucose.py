#!/usr/bin/env python3
"""Glycémie (MCP Nightscout, LECTURE SEULE) autour des séances vélo — calcul déterministe.

    python3 scripts/arc_glucose.py precheck --mgdl 104 --direction Flat [--intensity threshold] [--duration-s 3600]
    python3 scripts/arc_glucose.py session  --start ISO --end ISO --glucose g.json [--treatments t.json]
    python3 scripts/arc_glucose.py day      --glucose g.json

Entrées : la réponse JSON brute de `get_glucose_by_date_range` (`{"result":[{"glucose_mgdl",
"direction","timestamp"}…]}`) et de `get_treatments_by_date`. Sortie : JSON.

Ce script ne DOSE RIEN, ne recommande AUCUN changement d'insuline, de basale ni d'override Loop :
il décrit ce qui s'est passé et rappelle des repères de consensus sur les glucides avant l'effort
(adaptés de Riddell et al., Lancet Diabetes Endocrinol 2017). Ce sont des « approximations du projet »,
pas un avis médical ; la décision appartient à l'athlète et à son équipe de diabétologie.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coach_config  # noqa: E402

FALLING = {"SingleDown", "DoubleDown", "FortyFiveDown"}
RISING = {"SingleUp", "DoubleUp", "FortyFiveUp"}
HARD = {"threshold", "vo2max", "anaerobic", "race"}
LATE_HYPO_WINDOW_H = 24     # le risque d'hypoglycémie tardive persiste jusqu'à ~24 h après l'effort
POST_WINDOW_H = 2           # fenêtre « récupération immédiate » analysée


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _entries(doc):
    rows = doc.get("result", doc) if isinstance(doc, dict) else doc
    out = []
    for r in rows or []:
        v = r.get("glucose_mgdl", r.get("sgv"))
        ts = r.get("timestamp") or r.get("dateString")
        if v is None or ts is None:
            continue
        out.append({"t": _dt(ts), "mgdl": v, "dir": r.get("direction")})
    return sorted(out, key=lambda e: e["t"])


def precheck(mgdl, direction=None, intensity="endurance", duration_s=3600, thresholds=None):
    th = thresholds or {}
    stop, low, ok_low, ok_high, high = (th.get("stop_below_mgdl", 70), th.get("start_low_mgdl", 90),
                                        th.get("start_target_low_mgdl", 126),
                                        th.get("start_target_high_mgdl", 180),
                                        th.get("start_high_mgdl", 250))
    falling = direction in FALLING
    rising = direction in RISING
    hard = intensity in HARD
    if mgdl < stop:
        cat, carbs, msg = "hypo", "15-20 g de glucides rapides, recontrôler 15 min, ne pas démarrer", "Hypoglycémie : on traite d'abord, la séance attend."
    elif mgdl < low:
        cat, carbs, msg = "bas", "10-20 g de glucides rapides avant de démarrer", "Trop bas pour démarrer : glucides d'abord, puis vérifier la tendance."
    elif mgdl < ok_low:
        cat = "limite_basse"
        carbs = "10-15 g avant et ravitaillement dès le début" if (falling or duration_s > 3600) else "≈ 10 g avant"
        msg = "Zone basse pour démarrer : glucides avant et à portée de main."
    elif mgdl <= ok_high:
        cat, carbs, msg = "cible", ("5-10 g si la glycémie descend" if falling else "aucun avant"), "Bonne fenêtre pour démarrer."
    elif mgdl <= high:
        cat, carbs = "haute_acceptable", "aucun"
        msg = ("Un peu haute : l'effort aérobie la fera descendre ; à haute intensité elle peut monter."
               if hard else "Un peu haute : démarrage possible sur un effort aérobie.")
    else:
        cat, carbs = "haute", "aucun"
        msg = "Haute : vérifier les cétones et l'insuline active avant tout effort intense ; sinon séance facile ou report."
    if falling and cat in ("cible", "limite_basse", "bas"):
        msg += " Tendance descendante : prévoir plus de glucides."
    if rising and cat == "haute":
        msg += " Tendance montante."
    return {"glucose_mgdl": mgdl, "direction": direction, "category": cat,
            "carbs_before": carbs, "message": msg,
            "reminders": ["Aucune dose d'insuline ni modification de basale/override n'est décidée ici : "
                          "décision de l'athlète et de son équipe de diabétologie.",
                          "Emporter des glucides rapides à chaque séance (hypoglycémie possible pendant et jusqu'à ~24 h après)."],
            "disclaimer": "ce n'est pas un avis médical (repères de consensus, approximation du projet)"}


def day(doc, low=70, high=180):
    es = _entries(doc)
    if not es:
        return {"error": "aucune donnée de glycémie — mesure absente, rien n'est inventé"}
    vals = [e["mgdl"] for e in es]
    n = len(vals)
    mean = sum(vals) / n
    sd = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5
    out = {"n": n, "avg_mgdl": round(mean), "min_mgdl": min(vals), "max_mgdl": max(vals),
           "tir_pct": round(100 * sum(low <= v <= high for v in vals) / n),
           "time_below_pct": round(100 * sum(v < low for v in vals) / n, 1),
           "time_above_pct": round(100 * sum(v > high for v in vals) / n),
           "cv_pct": round(100 * sd / mean) if mean else None,
           "lows_below_54": sum(v < 54 for v in vals)}
    if n < 144:
        out["warning"] = "moins de 12 h de capteur : statistiques indicatives"
    return out


def _treat(doc, start, end):
    carbs, overrides = 0.0, []
    rows = doc.get("result", doc) if isinstance(doc, dict) else (doc or [])
    for t in rows:
        ts = t.get("timestamp") or t.get("created_at")
        if not ts:
            continue
        when = _dt(ts)
        if t.get("eventType") == "Temporary Override":
            dur = timedelta(minutes=t.get("duration") or 0)
            if when <= end and when + dur >= start:
                overrides.append({"reason": t.get("reason"), "at": ts,
                                  "insulin_scale": t.get("insulinNeedsScaleFactor"),
                                  "correction_range": t.get("correctionRange")})
        elif t.get("carbs") and start - timedelta(minutes=30) <= when <= end:
            carbs += float(t["carbs"])
    return round(carbs) if carbs else None, overrides


def session(doc, start, end, treatments=None, low=70):
    s, e = _dt(start), _dt(end)
    es = _entries(doc)
    if not es:
        return {"error": "aucune donnée de glycémie sur la fenêtre — mesure absente"}
    before = [x for x in es if x["t"] <= s]
    during = [x for x in es if s <= x["t"] <= e]
    after = [x for x in es if e < x["t"] <= e + timedelta(hours=POST_WINDOW_H)]
    out = {"window": {"start": start, "end": end}}
    if before and s - before[-1]["t"] <= timedelta(minutes=15):
        out["glucose_start_mgdl"], out["direction_start"] = before[-1]["mgdl"], before[-1]["dir"]
    else:
        out["start_note"] = "pas de lecture dans les 15 min avant le départ"
    if during:
        vals = [x["mgdl"] for x in during]
        out["glucose_min_mgdl"], out["glucose_max_mgdl"] = min(vals), max(vals)
        out["glucose_end_mgdl"] = during[-1]["mgdl"]
        if len(during) >= 2:
            hrs = (during[-1]["t"] - during[0]["t"]).total_seconds() / 3600
            if hrs > 0.25:
                out["slope_mgdl_per_h"] = round((during[-1]["mgdl"] - during[0]["mgdl"]) / hrs)
    if after:
        out["glucose_post_min_mgdl"] = min(x["mgdl"] for x in after)
    low_pts = [x for x in during + after if x["mgdl"] < low]
    out["hypo_events"] = 1 if low_pts else 0
    if low_pts:
        out["first_low"] = {"mgdl": low_pts[0]["mgdl"], "at": low_pts[0]["t"].isoformat()}
    if treatments is not None:
        carbs, ov = _treat(treatments, s, e)
        if carbs:
            out["carbs_logged_g"] = carbs
        if ov:
            out["overrides"] = ov
    flags = []
    if out["hypo_events"]:
        flags.append(f"glycémie < {low} mg/dL pendant ou dans les {POST_WINDOW_H} h qui suivent")
    if out.get("glucose_start_mgdl", 999) < 90:
        flags.append("départ sous 90 mg/dL")
    flags.append(f"surveillance des hypoglycémies tardives jusqu'à ~{LATE_HYPO_WINDOW_H} h après l'effort")
    out["flags"] = flags
    out["disclaimer"] = "ce n'est pas un avis médical"
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, a, opt = argv[1], argv[2:], {}
    while a:
        k = a.pop(0)
        if k.startswith("--"):
            opt[k[2:]] = a.pop(0)
    cfg = coach_config.load()
    g = cfg.get("glucose", {})
    load = lambda p: json.load(open(p, encoding="utf-8"))  # noqa: E731
    low = int(g.get("low_mgdl", 70))
    if cmd == "precheck":
        res = precheck(float(opt["mgdl"]), opt.get("direction"), opt.get("intensity", "endurance"),
                       float(opt.get("duration-s", 3600)), g)
    elif cmd == "session":
        res = session(load(opt["glucose"]), opt["start"], opt["end"],
                      load(opt["treatments"]) if "treatments" in opt else None, low)
    elif cmd == "day":
        res = day(load(opt["glucose"]), low, int(g.get("high_mgdl", 180)))
    else:
        print(__doc__)
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 1 if "error" in res else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
