#!/usr/bin/env python3
"""Contrat de données : chaque fichier persisté s'ouvre par UN bloc ```arc de JSON.

    python3 scripts/arc_contract.py --validate <fichier> [<fichier> …]

Clés en anglais, unités SI (mètres, secondes, bpm, watts, kg, kcal) quelle que soit
`[athlete].units`, mesure absente = clé omise (jamais 0). Le texte libre reste sous
le bloc. Voir le skill `workspace-data-contract` pour le détail par type.
"""
import json
import os
import re
import sys

BLOCK = re.compile(r"```arc\s*\n(.*?)\n```", re.S)

DISCIPLINES = {"route", "cx", "poids", "strength", "other"}
INTENSITIES = {"rest", "recovery", "endurance", "tempo", "threshold", "vo2max",
               "anaerobic", "race", "strength"}
VERDICTS = {"green", "amber", "red"}
LOAD_METHODS = {"power", "hr", "trimp", "rpe"}
OUTCOMES = {"proposed", "applied", "superseded", "declined"}

# type -> (clés obligatoires, validateurs de champs {clé: (types, enum|None)})
SCHEMAS = {
    "activity": (["date", "discipline", "duration_s"], {
        "date": (str, None), "discipline": (str, DISCIPLINES), "duration_s": ((int, float), None),
        "distance_m": ((int, float), None), "elevation_gain_m": ((int, float), None),
        "avg_hr_bpm": ((int, float), None), "max_hr_bpm": ((int, float), None),
        "avg_power_w": ((int, float), None), "np_w": ((int, float), None),
        "rpe": ((int, float), None), "load": ((int, float), None),
        "load_method": (str, LOAD_METHODS), "intensity": (str, INTENSITIES),
        "calories_kcal": ((int, float), None), "carbs_g": ((int, float), None),
        "fluid_intake_ml": ((int, float), None), "weight_pre_kg": ((int, float), None),
        "weight_post_kg": ((int, float), None), "ow_ids": (list, None),
        "sources": (list, None), "gear_ids": (list, None), "race": (bool, None),
        "glucose_start_mgdl": ((int, float), None), "glucose_min_mgdl": ((int, float), None),
        "glucose_max_mgdl": ((int, float), None), "glucose_end_mgdl": ((int, float), None),
        "glucose_post_min_mgdl": ((int, float), None), "hypo_events": (int, None),
        "carbs_logged_g": ((int, float), None), "carbs_before_g": ((int, float), None),
        "loop_override": (str, None),
    }),
    "health": (["date"], {
        "date": (str, None), "resting_hr_bpm": ((int, float), None),
        "hrv_rmssd_ms": ((int, float), None), "sleep_min": ((int, float), None),
        "verdict": (str, VERDICTS), "verdict_reason": (str, None),
        "pain": (list, None), "weight_kg": ((int, float), None),
        "body_fat_pct": ((int, float), None), "cycle_phase": (str, None),
        "cycle_day": ((int, float), None),
        "glucose_avg_mgdl": ((int, float), None), "tir_pct": ((int, float), None),
        "time_below_pct": ((int, float), None), "time_above_pct": ((int, float), None),
        "glucose_cv_pct": ((int, float), None), "lows_below_54": (int, None),
        "nocturnal_low": (bool, None),
    }),
    "nutrition": (["date"], {
        "date": (str, None), "intake_kcal": ((int, float), None),
        "protein_g": ((int, float), None), "carbs_g": ((int, float), None),
        "fat_g": ((int, float), None), "deficit_kcal": ((int, float), None),
        "burned_kcal": ((int, float), None), "energy_availability": ((int, float), None),
    }),
    "week": (["week_start", "sessions"], {
        "week_start": (str, None), "sessions": (list, None), "phase": (str, None),
        "focus": (str, None), "deficit_kcal_by_date": (dict, None),
    }),
    "decision": (["date", "trigger", "outcome"], {
        "date": (str, None), "trigger": (str, None), "outcome": (str, OUTCOMES),
        "rule_ids": (list, None), "before": (dict, None), "after": (dict, None),
        "session_ref": (str, None), "supersedes": (str, None), "inputs": (dict, None),
    }),
    "report": (["date", "period_start", "period_end"], {
        "date": (str, None), "period_start": (str, None), "period_end": (str, None),
        "report_type": (str, None), "load": (dict, None), "weight": (dict, None),
    }),
    "athlete_profile": (["type"], {
        "ftp_w": ((int, float), None), "lthr_bpm": ((int, float), None),
        "hr_max_bpm": ((int, float), None), "hr_rest_bpm": ((int, float), None),
        "weight_kg": ((int, float), None), "target_weight_kg": ((int, float), None),
        "height_cm": ((int, float), None), "birth_year": (int, None),
        "sex": (str, {"m", "f"}), "body_fat_pct": ((int, float), None),
        "disciplines": (list, None), "available_days": (list, None),
    }),
    "objective": (["name", "date", "discipline"], {
        "name": (str, None), "date": (str, None), "discipline": (str, DISCIPLINES),
        "kind": (str, None), "priority": (str, {"A", "B", "C"}),
        "target_weight_kg": ((int, float), None), "target_date": (str, None),
    }),
}
SESSION_REQUIRED = ["date", "discipline", "title"]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def extract(text):
    m = BLOCK.search(text)
    if not m:
        return None
    return json.loads(m.group(1))


def _check_fields(obj, spec, where, errs):
    for key, (types, enum) in spec.items():
        if key not in obj:
            continue
        v = obj[key]
        if v is None:
            errs.append(f"{where}{key} : null interdit — omettre la clé (mesure absente)")
            continue
        if not isinstance(v, types) or (isinstance(v, bool) and types is not bool):
            errs.append(f"{where}{key} : type invalide ({type(v).__name__})")
            continue
        if enum and v not in enum:
            errs.append(f"{where}{key} : « {v} » hors de {sorted(enum)}")
        if key.endswith("date") or key in ("week_start", "period_start", "period_end"):
            if isinstance(v, str) and not DATE.match(v):
                errs.append(f"{where}{key} : date AAAA-MM-JJ attendue")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0 \
                and key not in ("fluid_intake_ml", "deficit_kcal", "carbs_g", "hypo_events",
                                    "time_below_pct", "time_above_pct", "lows_below_54"):
            errs.append(f"{where}{key} : 0 interdit — mesure absente = clé omise")


def validate_obj(obj):
    errs = []
    t = obj.get("type")
    if t not in SCHEMAS:
        return [f"type « {t} » inconnu — attendu : {sorted(SCHEMAS)}"]
    required, spec = SCHEMAS[t]
    for k in required:
        if k not in obj:
            errs.append(f"clé obligatoire manquante : {k}")
    _check_fields(obj, spec, "", errs)
    if t == "week" and isinstance(obj.get("sessions"), list):
        import datetime as dt
        try:
            monday = dt.date.fromisoformat(obj["week_start"])
            if monday.weekday() != 0:
                errs.append("week_start doit être un lundi")
        except (KeyError, ValueError):
            monday = None
        for i, s in enumerate(obj["sessions"]):
            w = f"sessions[{i}]."
            for k in SESSION_REQUIRED:
                if k not in s:
                    errs.append(f"{w}{k} manquant")
            _check_fields(s, {"date": (str, None), "discipline": (str, DISCIPLINES),
                              "title": (str, None), "duration_s": ((int, float), None),
                              "intensity": (str, INTENSITIES), "key": (bool, None),
                              "garmin_workout_id": ((int, str), None)}, w, errs)
            if monday and isinstance(s.get("date"), str) and DATE.match(s["date"]):
                d = dt.date.fromisoformat(s["date"])
                if not 0 <= (d - monday).days <= 6:
                    errs.append(f"{w}date hors de la semaine {obj['week_start']}")
    return errs


def validate_file(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        obj = extract(text)
    except json.JSONDecodeError as e:
        return [f"JSON invalide : {e}"]
    if obj is None:
        return ["aucun bloc ```arc trouvé"]
    # le bloc doit suivre immédiatement le titre
    head = text.lstrip().split("```arc", 1)[0]
    if head.count("\n") > 3 and not head.lstrip().startswith("#"):
        return ["le bloc ```arc doit suivre le titre"]
    return validate_obj(obj)


def main(argv):
    if len(argv) < 3 or argv[1] != "--validate":
        print(__doc__)
        return 2
    bad = 0
    for p in argv[2:]:
        errs = validate_file(p) if os.path.exists(p) else ["fichier introuvable"]
        if errs:
            bad += 1
            print(f"✗ {p}")
            for e in errs:
                print(f"    - {e}")
        else:
            print(f"✓ {p}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
