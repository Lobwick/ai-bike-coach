#!/usr/bin/env python3
"""Perte de poids compatible avec l'entraînement vélo : arithmétique déterministe.

    python3 scripts/arc_weight.py trend   < daily.json     # tendance de poids (sortie de arc_ow.py daily)
    python3 scripts/arc_weight.py plan    --weight 79 --target 74 --weeks 12 [--profile …]
    python3 scripts/arc_weight.py bmr     [--profile …]
    python3 scripts/arc_weight.py fuel    --duration-s 10800 --intensity tempo [--weight 79]
    python3 scripts/arc_weight.py ea      --intake 2400 --exercise 900 --ffm 66

Le modèle raisonne, ce script calcule. Tous les repères sont des « approximations du
projet » (équations publiées, marges d'erreur individuelles importantes) — jamais un
avis médical. Une perte plus rapide que `r6_weight_loss_max_pct_per_week`, une énergie
disponible sous le plancher, ou un poids cible sous un IMC de 18,5 déclenchent une
consultation, pas un ajustement.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_cycling  # noqa: E402
import coach_config  # noqa: E402

KCAL_PER_KG_FAT = 7700  # repère courant ; la perte réelle mêle masse grasse et eau/glycogène


def bmr_mifflin(weight_kg, height_cm, age, sex):
    """Mifflin-St Jeor (1990) — kcal/jour au repos."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + (5 if sex == "m" else -161)


def weight_trend(days, alpha=0.1):
    """Moyenne exponentielle des pesées (lisse eau/glycogène). days : [{date, weight_kg}]."""
    pts = [(d["date"], d["weight_kg"]) for d in days if d.get("weight_kg")]
    if not pts:
        return {"error": "aucune pesée — mesure absente, rien n'est inventé"}
    ema, series = pts[0][1], []
    for date, w in pts:
        ema += alpha * (w - ema)
        series.append({"date": date, "weight_kg": w, "trend_kg": round(ema, 2)})
    out = {"series": series, "latest_trend_kg": series[-1]["trend_kg"], "n": len(pts)}
    if len(series) >= 2:
        d0 = math.floor(_ord(series[0]["date"]))
        d1 = math.floor(_ord(series[-1]["date"]))
        weeks = max((d1 - d0) / 7, 1e-9)
        out["trend_kg_per_week"] = round((series[-1]["trend_kg"] - series[0]["trend_kg"]) / weeks, 2)
        if len(pts) < 5 or (d1 - d0) < 14:
            out["warning"] = "moins de 5 pesées / 14 jours : tendance indicative seulement"
    return out


def _ord(iso):
    import datetime as dt
    return dt.date.fromisoformat(iso[:10]).toordinal()


def plan(weight, target, weeks, cfg):
    loss = weight - target
    max_pct = coach_config.get(cfg, "guardrails.r6_weight_loss_max_pct_per_week", 1.0)
    rate_kg_wk = loss / weeks
    rate_pct = 100 * rate_kg_wk / weight
    deficit = rate_kg_wk * KCAL_PER_KG_FAT / 7
    cap = coach_config.get(cfg, "guardrails.r7_deficit_max_kcal", 300)
    out = {"loss_kg": round(loss, 1), "rate_kg_per_week": round(rate_kg_wk, 2),
           "rate_pct_per_week": round(rate_pct, 2),
           "average_daily_deficit_kcal": round(deficit),
           "within_guardrail": rate_pct <= max_pct,
           "guardrail_max_pct_per_week": max_pct,
           "key_day_deficit_cap_kcal": cap,
           "assumption": f"{KCAL_PER_KG_FAT} kcal/kg de masse grasse — approximation du projet"}
    if rate_pct > max_pct:
        safe_weeks = math.ceil(loss / (weight * max_pct / 100))
        out["suggestion"] = f"durée mini compatible avec le garde-fou : {safe_weeks} semaines"
    return out


def fueling(duration_s, intensity, weight=None):
    """Glucides pendant l'effort (g/h). Repères de consensus (ACSM/IOC), pas une prescription."""
    h = duration_s / 3600
    hard = intensity in ("tempo", "threshold", "vo2max", "anaerobic", "race")
    if h < 1:
        g = (0, 0)
    elif h < 2:
        g = (30, 60) if hard else (0, 30)
    elif h < 3:
        g = (60, 80) if hard else (30, 60)
    else:
        g = (80, 100) if hard else (60, 90)
    out = {"duration_h": round(h, 2), "carbs_g_per_h": {"low": g[0], "high": g[1]},
           "carbs_g_total": {"low": round(g[0] * h), "high": round(g[1] * h)},
           "fluid_ml_per_h": {"low": 400, "high": 800},
           "note": "au-delà de ~60 g/h : mélange glucose:fructose, intestin à entraîner ; "
                   "en phase de déficit, ne jamais couper le ravitaillement d'une séance clé"}
    if weight:
        out["recovery_carbs_g"] = round(1.0 * weight) if h >= 1.5 and hard else None
        out["recovery_protein_g"] = round(0.3 * weight)
        out = {k: v for k, v in out.items() if v is not None}
    return out


def energy_availability(intake_kcal, exercise_kcal, ffm_kg):
    ea = (intake_kcal - exercise_kcal) / ffm_kg
    status = "ok" if ea >= 45 else "bas" if ea >= 30 else "critique"
    return {"energy_availability_kcal_per_kg_ffm": round(ea, 1), "status": status,
            "thresholds": "≥ 45 optimal · 30-45 bas · < 30 risque RED-S (consulter)",
            "disclaimer": "ce n'est pas un avis médical"}


def _profile(opt, root):
    return arc_cycling.read_profile(os.path.join(root, opt.get("profile", "planning/Athlete_Profile.md")))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, args = argv[1], argv[2:]
    opt = {}
    while args:
        a = args.pop(0)
        if a.startswith("--"):
            opt[a[2:]] = args.pop(0) if args and not args[0].startswith("--") else True
    root = opt.get("workspace", coach_config.ROOT)
    cfg = coach_config.load(root)
    if cmd == "trend":
        doc = json.load(sys.stdin)
        print(json.dumps(weight_trend(doc.get("days", doc)), ensure_ascii=False, indent=2))
        return 0
    if cmd == "plan":
        out = plan(float(opt["weight"]), float(opt["target"]), float(opt["weeks"]), cfg)
        prof = _profile(opt, root)
        if prof.get("height_cm"):
            bmi = float(opt["target"]) / (prof["height_cm"] / 100) ** 2
            out["target_bmi"] = round(bmi, 1)
            if bmi < 18.5:
                out["consult"] = "IMC cible < 18,5 : ne pas planifier, orienter vers un professionnel de santé"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if cmd == "bmr":
        import datetime as dt
        p = _profile(opt, root)
        need = [k for k in ("weight_kg", "height_cm", "birth_year", "sex") if k not in p]
        if need:
            print(json.dumps({"error": f"profil incomplet : {need}"}, ensure_ascii=False))
            return 1
        age = dt.date.today().year - p["birth_year"]
        print(json.dumps({"bmr_kcal": round(bmr_mifflin(p["weight_kg"], p["height_cm"], age, p["sex"])),
                          "equation": "Mifflin-St Jeor"}, ensure_ascii=False))
        return 0
    if cmd == "fuel":
        print(json.dumps(fueling(float(opt["duration-s"]), opt.get("intensity", "endurance"),
                                 float(opt["weight"]) if "weight" in opt else None),
                         ensure_ascii=False, indent=2))
        return 0
    if cmd == "ea":
        print(json.dumps(energy_availability(float(opt["intake"]), float(opt["exercise"]),
                                             float(opt["ffm"])), ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
