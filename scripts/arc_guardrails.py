#!/usr/bin/env python3
"""Garde-fous déterministes : un second avis calculé, avant d'écrire ou de pousser une semaine.

    python3 scripts/arc_guardrails.py check --week planning/Semaine_2026-10-12.md [--today AAAA-MM-JJ]
    python3 scripts/arc_guardrails.py check --week - < semaine.json

Codes de sortie : 0 = ok (avec éventuels warn/info) · 1 = au moins un `block` · 2 = entrée invalide.

R1 rampe de condition projetée   R2 saut de charge hebdomadaire   R3 jours durs consécutifs
R4 forme projetée trop basse     R5 qualité après verdict rouge   R6 vitesse de perte de poids
R7 déficit un jour de séance clé

Seuils et sévérités : `config/workspace.toml` → [guardrails]. La charge planifiée est une
ESTIMATION (durée × facteur d'intensité², voir arc_cycling.IF_BY_INTENSITY), jamais une mesure.
Les repères viennent de la littérature (rampe, monotonie, RED-S) mais le seuil exact de
blessure ou de surentraînement n'est pas établi : ils avertissent, ils ne diagnostiquent pas.
"""
import datetime as dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_contract  # noqa: E402
import arc_cycling  # noqa: E402
import coach_config  # noqa: E402

HARD = {"threshold", "vo2max", "anaerobic", "race"}
QUALITY = {"tempo", "threshold", "vo2max", "anaerobic", "race"}
MIN_HISTORY_DAYS = 42


def _sev(cfg, rule_key, default="warn"):
    return coach_config.get(cfg, f"guardrails.severity_{rule_key}", default)


def _viol(rule, sev, message, **inputs):
    v = {"rule": rule, "severity": sev, "message": message}
    if inputs:
        v["inputs"] = inputs
    return v


def _load_week(path):
    if path == "-":
        obj = json.load(sys.stdin)
    else:
        with open(path, encoding="utf-8") as fh:
            obj = arc_contract.extract(fh.read())
    if obj is None:
        raise ValueError("aucun bloc arc / JSON")
    if "week_start" not in obj or "sessions" not in obj:
        raise ValueError("week_start / sessions manquants")
    return obj


def _latest_red(root, today):
    """Dernier verdict rouge dans medical/*_health.md des 3 derniers jours."""
    reds = []
    for p in glob.glob(os.path.join(root, "medical", "*_health.md")):
        try:
            with open(p, encoding="utf-8") as fh:
                o = arc_contract.extract(fh.read())
        except (OSError, json.JSONDecodeError):
            continue
        if o and o.get("verdict") == "red" and o.get("date"):
            d = dt.date.fromisoformat(o["date"])
            if 0 <= (today - d).days <= 3:
                reds.append(d)
    return max(reds) if reds else None


def check(week, root, today, weight_trend_pct=None):
    cfg = coach_config.load(root)
    g = lambda k, d: coach_config.get(cfg, f"guardrails.{k}", d)  # noqa: E731
    if not g("enabled", True):
        return {"ok": True, "violations": [], "note": "garde-fous désactivés"}
    out = []
    monday = dt.date.fromisoformat(week["week_start"])
    sessions = sorted(week["sessions"], key=lambda s: s["date"])

    # charge planifiée par jour (estimation)
    planned = {}
    for s in sessions:
        pl = s.get("planned_load")
        if pl is None and s.get("duration_s") and s.get("intensity"):
            pl = arc_cycling.planned_load(s["duration_s"], s["intensity"])
        if pl:
            planned[s["date"]] = planned.get(s["date"], 0.0) + pl
    week_total = round(sum(planned.values()), 1)

    state = arc_cycling.current_state(root, today, 120, cfg)
    reliable = state["reliable"]
    hist = {r["date"]: r["load"] for r in state["series"]}

    # R1 / R4 — projection condition & forme sur la semaine proposée
    if reliable and state["state"]:
        merged = dict(hist)
        merged.update(planned)
        end = monday + dt.timedelta(days=6)
        daily_in = {d: v for d, v in merged.items() if d <= end.isoformat()}
        # on rejoue depuis le début de l'historique pour garder la mémoire exponentielle
        first = min(dt.date.fromisoformat(d) for d in daily_in)
        proj = arc_cycling.series(daily_in, first, max(end, today),
                                  coach_config.get(cfg, "load.condition_days", 42),
                                  coach_config.get(cfg, "load.fatigue_days", 7))
        wk = [r for r in proj if monday.isoformat() <= r["date"] <= end.isoformat()]
        before = next((r for r in proj if r["date"] == (monday - dt.timedelta(days=1)).isoformat()), None)
        if wk and before:
            ramp = round(wk[-1]["condition"] - before["condition"], 1)
            if ramp > g("r1_ramp_max_per_week", 8.0):
                out.append(_viol("R1", _sev(cfg, "r1_ramp"),
                                 f"rampe de condition projetée +{ramp}/semaine (> {g('r1_ramp_max_per_week', 8.0)})",
                                 ramp=ramp, threshold=g("r1_ramp_max_per_week", 8.0)))
            low = min(wk, key=lambda r: r["form"])
            if low["form"] < g("r4_form_floor", -30.0):
                out.append(_viol("R4", _sev(cfg, "r4_form_floor"),
                                 f"forme projetée {low['form']} le {low['date']} (plancher {g('r4_form_floor', -30.0)}) : prévoir une séance facile ou du repos",
                                 form=low["form"], date=low["date"]))
    else:
        out.append(_viol("R1", "info",
                         f"historique de charge < {MIN_HISTORY_DAYS} j ({state['history_days']} j) : R1/R2/R4 non évaluées"))

    # R2 — saut de charge hebdo vs moyenne des 4 semaines précédentes
    if reliable:
        prev = []
        for i in range(1, 5):
            ws = monday - dt.timedelta(weeks=i)
            prev.append(sum(hist.get((ws + dt.timedelta(days=k)).isoformat(), 0.0) for k in range(7)))
        ref = sum(prev) / 4
        if ref > 0 and week_total > 0:
            pct = round(100 * (week_total / ref - 1), 1)
            if pct > g("r2_weekly_load_increase_max_pct", 15.0):
                out.append(_viol("R2", _sev(cfg, "r2_weekly_load_jump"),
                                 f"charge hebdo planifiée {week_total} (+{pct} % vs moyenne 4 sem. = {round(ref, 1)}, seuil {g('r2_weekly_load_increase_max_pct', 15.0)} %)",
                                 planned=week_total, reference=round(ref, 1), pct=pct))

    # R3 — jours durs consécutifs
    run, best, best_end = 0, 0, None
    for i in range(7):
        d = (monday + dt.timedelta(days=i)).isoformat()
        if any(s["date"] == d and s.get("intensity") in HARD for s in sessions):
            run += 1
            if run > best:
                best, best_end = run, d
        else:
            run = 0
    if best > g("r3_consecutive_hard_max", 2):
        out.append(_viol("R3", _sev(cfg, "r3_consecutive_hard"),
                         f"{best} jours d'intensité consécutifs (max {g('r3_consecutive_hard_max', 2)}) jusqu'au {best_end}",
                         run=best))

    # R5 — qualité après verdict santé rouge
    red = _latest_red(root, today)
    if red:
        for s in sessions:
            sd = dt.date.fromisoformat(s["date"])
            if s.get("intensity") in QUALITY and 0 <= (sd - red).days <= 1:
                out.append(_viol("R5", _sev(cfg, "r5_quality_after_red", "block"),
                                 f"séance {s['intensity']} le {s['date']} dans les 24 h d'un verdict santé rouge ({red})",
                                 session=s["date"], red_date=red.isoformat()))

    # R6 — vitesse de perte de poids (tendance fournie par arc_weight.py trend)
    if weight_trend_pct is not None and weight_trend_pct < -g("r6_weight_loss_max_pct_per_week", 1.0):
        out.append(_viol("R6", _sev(cfg, "r6_weight_loss_rate"),
                         f"perte de poids {abs(weight_trend_pct)} %/semaine (max {g('r6_weight_loss_max_pct_per_week', 1.0)} %) : réduire le déficit",
                         pct_per_week=weight_trend_pct))

    # R7 — déficit un jour de séance clé
    cap = g("r7_deficit_max_kcal", 300)
    for d, deficit in (week.get("deficit_kcal_by_date") or {}).items():
        for s in sessions:
            if s["date"] != d:
                continue
            key = s.get("key") or (s.get("intensity") in HARD and s.get("duration_s", 0) >= 5400) \
                or s.get("duration_s", 0) >= 10800
            if key and deficit > cap:
                out.append(_viol("R7", _sev(cfg, "r7_deficit_on_key_day"),
                                 f"déficit {deficit} kcal le {d} (séance clé « {s.get('title')} », plafond {cap} kcal)",
                                 deficit_kcal=deficit, cap=cap))

    blocked = any(v["severity"] == "block" for v in out)
    return {"ok": not blocked, "week_start": week["week_start"], "planned_load": week_total,
            "history_days": state["history_days"], "violations": out}


def main(argv):
    if len(argv) < 2 or argv[1] != "check":
        print(__doc__)
        return 2
    opt, a = {}, argv[2:]
    while a:
        k = a.pop(0)
        if k.startswith("--"):
            opt[k[2:]] = a.pop(0)
    try:
        today = dt.date.fromisoformat(opt["today"]) if "today" in opt else dt.date.today()
        week = _load_week(opt["week"])
        res = check(week, opt.get("workspace", coach_config.ROOT), today,
                    float(opt["weight-pct-week"]) if "weight-pct-week" in opt else None)
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e) or repr(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
