#!/usr/bin/env python3
"""Tableau de bord local en LECTURE SEULE (stdlib, aucune dépendance, aucun appel réseau sortant).

    python3 scripts/arc_serve.py [--port 8765] [--workspace .]

- Par défaut, écoute UNIQUEMENT sur 127.0.0.1 ; si le port est pris, les 9 suivants sont essayés.
  Déploiement derrière un proxy (Freebox/Traefik) : `ARC_LISTEN=0.0.0.0` n'est accepté QUE si `ARC_ALLOWED_HOSTS` (noms
  d'hôte autorisés, séparés par des virgules) ET `ARC_PROXY_AUTH=1` (« un proxy authentifie devant moi ») sont posés ;
  sinon le serveur refuse de démarrer. Jamais d'accès sans authentification sur autre chose que la boucle locale.
- GET seulement ; l'en-tête Host doit être localhost / 127.0.0.1 ou un hôte de `ARC_ALLOWED_HOSTS` (« DNS rebinding »).
- CSP stricte : aucun script ni style inline. SEULE ressource externe, comme dans le tableau de bord d'origine :
  les polices Sora/Inter de Google Fonts, désactivables par `[dashboard].web_fonts = false` (repli sur les polices du
  système). Le texte venant des fichiers est échappé par défaut avant d'entrer dans le DOM (`h` dans `web/js/app.js`).
- Ne lit que les fichiers du workspace déjà persistés ; n'interroge ni Open Wearables, ni Nightscout, ni Garmin,
  et n'écrit rien. La glycémie affichée est celle que les agents ont déjà écrite dans les fichiers.
"""
import datetime as dt
import glob
import http.server
import json
import os
import re
import socketserver
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_contract  # noqa: E402
import arc_cycling  # noqa: E402
import arc_guardrails  # noqa: E402
import coach_config  # noqa: E402

ROOT = coach_config.ROOT
WEB = os.path.join(ROOT, "web")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/css/app.css": ("css/app.css", "text/css; charset=utf-8"),
          "/js/app.js": ("js/app.js", "text/javascript; charset=utf-8"),
          "/js/chart.js": ("js/chart.js", "text/javascript; charset=utf-8"),
          "/js/format.js": ("js/format.js", "text/javascript; charset=utf-8"),
          "/js/nav.js": ("js/nav.js", "text/javascript; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}
FONTS_CSS = ('@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
             '&family=Sora:wght@600;700&display=swap");\n')


def csp(web_fonts):
    style = "style-src 'self' https://fonts.googleapis.com" if web_fonts else "style-src 'self'"
    font = "font-src https://fonts.gstatic.com; " if web_fonts else ""
    return ("default-src 'none'; script-src 'self'; " + style + "; " + font + "connect-src 'self'; "
            "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _arc_files(root, sub, pattern="*.md"):
    out = []
    for p in sorted(glob.glob(os.path.join(root, sub, pattern))):
        try:
            with open(p, encoding="utf-8") as fh:
                obj = arc_contract.extract(fh.read())
        except (OSError, json.JSONDecodeError):
            continue
        if obj:
            out.append((os.path.relpath(p, root), obj))
    return out


def _weeks(root):
    return [o for _, o in _arc_files(root, "planning", "Semaine_*.md") if o.get("type") == "week"]


def _profile(root, cfg):
    return arc_cycling.read_profile(os.path.join(root, coach_config.get(cfg, "athlete.profile",
                                                                        "planning/Athlete_Profile.md")))


def _health(root):
    return [o for _, o in _arc_files(root, "medical", "*_health.md") if o.get("type") == "health"]


def api_summary(root, today=None):
    today = today or dt.date.today()
    cfg = coach_config.load(root)
    prof = _profile(root, cfg)
    st = arc_cycling.current_state(root, today, 90, cfg)
    health = _health(root)
    weights = [(h["date"], h["weight_kg"]) for h in health if h.get("weight_kg")]
    rhr = [h["resting_hr_bpm"] for h in health[-14:] if h.get("resting_hr_bpm")]
    races = sorted((s for w in _weeks(root) for s in w["sessions"] if s.get("race") and s["date"] >= today.isoformat()),
                   key=lambda s: s["date"])
    obj = next((o for _, o in _arc_files(root, "planning", "active_objective.md")), {})
    out = {"today": today.isoformat(), "objective": obj.get("name"),
           "disciplines": coach_config.get(cfg, "sport.disciplines", []),
           "units": coach_config.get(cfg, "athlete.units", "metric"),
           "profile": {k: prof[k] for k in ("ftp_w", "hr_rest_bpm", "hr_max_bpm", "lthr_bpm", "weight_kg", "sex")
                       if k in prof},
           "load": {"history_days": st["history_days"], "reliable": st["reliable"], "state": st["state"],
                    "ramp_per_week": st["ramp_per_week"]},
           "next_race": races[0] if races else None,
           "glucose_enabled": bool(coach_config.get(cfg, "glucose.enabled", False)),
           "weight_loss_locked": bool(coach_config.get(cfg, "weight_loss.medical_clearance_required", False)
                                      and not coach_config.get(cfg, "weight_loss.medical_clearance_confirmed", False))}
    if prof.get("ftp_w") and prof.get("weight_kg"):
        out["profile"]["w_per_kg"] = round(prof["ftp_w"] / prof["weight_kg"], 2)
    if weights:
        out["weight_latest"] = {"date": weights[-1][0], "kg": weights[-1][1], "n": len(weights)}
    if rhr:
        out["resting_hr_recent"] = sorted(rhr)[len(rhr) // 2]
    return out


def api_plan(root, today=None):
    today = today or dt.date.today()
    weeks = []
    for w in sorted(_weeks(root), key=lambda x: x["week_start"]):
        total = 0.0
        for s in w["sessions"]:
            pl = s.get("planned_load")
            if pl is None and s.get("duration_s") and s.get("intensity"):
                pl = arc_cycling.planned_load(s["duration_s"], s["intensity"])
            total += pl or 0
        try:
            g = arc_guardrails.check(w, root, today)
            viol = [{"rule": v["rule"], "severity": v["severity"], "message": v["message"]} for v in g["violations"]]
        except Exception as e:  # noqa: BLE001
            viol = [{"rule": "ERR", "severity": "info", "message": str(e)}]
        weeks.append({"week_start": w["week_start"], "phase": w.get("phase"), "focus": w.get("focus"),
                      "planned_load": round(total, 1), "sessions": w["sessions"], "guardrails": viol})
    return {"weeks": weeks}


def api_load(root, today=None):
    today = today or dt.date.today()
    cfg = coach_config.load(root)
    st = arc_cycling.current_state(root, today, 365, cfg)
    out = {"history_days": st["history_days"], "reliable": st["reliable"], "series": st["series"], "projection": [],
           "races": sorted(s["date"] for w in _weeks(root) for s in w["sessions"] if s.get("race")),
           "weekly_planned": [{"week_start": w["week_start"], "planned_load": w["planned_load"]}
                              for w in api_plan(root, today)["weeks"]]}
    if st["reliable"]:
        daily, _ = arc_cycling.build_daily(arc_cycling.read_activities(root), _profile(root, cfg))
        end = today
        for w in _weeks(root):
            for s in w["sessions"]:
                if s["date"] > today.isoformat():
                    pl = s.get("planned_load") or arc_cycling.planned_load(s.get("duration_s", 0), s.get("intensity", "")) or 0
                    daily[s["date"]] = daily.get(s["date"], 0) + pl
                    end = max(end, dt.date.fromisoformat(s["date"]))
        first = min(dt.date.fromisoformat(d) for d in daily) if daily else today
        ser = arc_cycling.series(daily, first, end, coach_config.get(cfg, "load.condition_days", 42),
                                 coach_config.get(cfg, "load.fatigue_days", 7))
        out["projection"] = [r for r in ser if r["date"] > today.isoformat()]
    else:
        out["note"] = (f"historique de charge {st['history_days']} j (< 42) : pas de projection de forme, "
                       "uniquement la charge planifiée par semaine")
    return out


def api_activities(root):
    keys = ("date", "discipline", "duration_s", "distance_m", "elevation_gain_m", "avg_hr_bpm", "max_hr_bpm", "load",
            "load_method", "intensity", "race", "easy_share_pct", "glucose_start_mgdl", "glucose_min_mgdl",
            "hypo_events", "carbs_g")
    rows = [{k: o[k] for k in keys if k in o} for _, o in _arc_files(root, "activities") if o.get("type") == "activity"]
    return {"activities": sorted(rows, key=lambda r: r["date"], reverse=True)[:40]}


def api_health(root):
    keys = ("date", "resting_hr_bpm", "hrv_rmssd_ms", "sleep_min", "verdict", "verdict_reason", "weight_kg",
            "tir_pct", "time_below_pct", "glucose_avg_mgdl", "lows_below_54", "nocturnal_low", "respiratory_rate_brpm",
            "spo2_pct")
    rows = [{k: h[k] for k in keys if k in h} for h in _health(root)]
    return {"days": sorted(rows, key=lambda r: r["date"])[-30:]}


_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")


def api_calendar(root, today=None):
    today = (today or dt.date.today()).isoformat()
    path = os.path.join(root, "resources", "calendrier-cx-ufolep-2026-2027.md")
    picked = {s["date"]: s.get("venue", "") for w in _weeks(root) for s in w["sessions"] if s.get("race")}
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = _ROW.match(line.strip())
                if m:
                    d, jour, lieu, orga = m.groups()
                    v = picked.get(d, "")
                    rows.append({"date": d, "day": jour, "place": lieu, "organizer": orga,
                                 "picked": bool(v) and v.lower().split(",")[0].split()[0] in lieu.lower(),
                                 "past": d < today})
    except OSError:
        return {"races": [], "note": "calendrier absent (resources/calendrier-cx-ufolep-2026-2027.md)"}
    return {"races": [r for r in rows if not r["past"]]}


def _mean_sd(vals):
    m = sum(vals) / len(vals)
    return m, (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5


METRICS = (("hrv_rmssd_ms", "HRV nocturne", "ms", 0), ("resting_hr_bpm", "FC de repos", "bpm", 0),
           ("sleep_min", "Sommeil", "min", 0), ("respiratory_rate_brpm", "Fréquence respiratoire", "/min", 1),
           ("spo2_pct", "SpO₂", "%", 1))


def api_today(root, today=None):
    """Bilan du jour : chaque mesure est comparée à la base PERSONNELLE (28 j précédents, ≥ 7 valeurs), jamais à une norme."""
    today = today or dt.date.today()
    iso = today.isoformat()
    health = sorted(_health(root), key=lambda h: h["date"])
    metrics = []
    for key, label, unit, digits in METRICS:
        pts = [(h["date"], h[key]) for h in health if key in h and h["date"] <= iso]
        if not pts:
            metrics.append({"key": key, "label": label, "unit": unit, "value": None})
            continue
        d, v = pts[-1]
        stale = (today - dt.date.fromisoformat(d)).days
        if stale > 3:
            metrics.append({"key": key, "label": label, "unit": unit, "value": None, "last": {"date": d, "value": v}})
            continue
        base = [x for dd, x in pts if dd < d][-28:]
        m = {"key": key, "label": label, "unit": unit, "digits": digits, "value": v, "date": d}
        if len(base) >= 7:
            mean, sd = _mean_sd(base)
            m["baseline"] = {"mean": round(mean, 1), "low": round(mean - sd, 1), "high": round(mean + sd, 1), "n": len(base)}
        metrics.append(m)
    ver = next((h for h in reversed(health) if h.get("verdict") and h["date"] <= iso), None)
    weeks = _weeks(root)
    sessions = sorted((s for w in weeks for s in w["sessions"]), key=lambda s: s["date"])
    cfg = coach_config.load(root)
    st = arc_cycling.current_state(root, today, 30, cfg)
    gl_day = next((h for h in reversed(health) if "tir_pct" in h), None)
    gl_act = next((a for a in sorted((o for _, o in _arc_files(root, "activities") if o.get("type") == "activity"),
                                     key=lambda a: a["date"], reverse=True) if "glucose_start_mgdl" in a), None)
    return {"date": iso, "metrics": metrics,
            "verdict": ({"value": ver["verdict"], "reason": ver.get("verdict_reason"), "date": ver["date"],
                         "is_today": ver["date"] == iso} if ver else None),
            "today_sessions": [s for s in sessions if s["date"] == iso],
            "upcoming": [s for s in sessions if s["date"] > iso][:4],
            "load": {"history_days": st["history_days"], "reliable": st["reliable"], "state": st["state"],
                     "ramp_per_week": st["ramp_per_week"]},
            "glucose": {"enabled": bool(coach_config.get(cfg, "glucose.enabled", False)),
                        "day": ({k: gl_day[k] for k in ("date", "tir_pct", "time_below_pct", "glucose_avg_mgdl",
                                                          "lows_below_54", "nocturnal_low") if k in gl_day} if gl_day else None),
                        "last_session": ({k: gl_act[k] for k in ("date", "glucose_start_mgdl", "glucose_min_mgdl",
                                                                   "glucose_max_mgdl", "hypo_events") if k in gl_act}
                                         if gl_act else None)}}


def api_decisions(root):
    rows = []
    for path, o in _arc_files(root, "planning", "*_decision_*.md"):
        if o.get("type") != "decision":
            continue
        try:
            with open(os.path.join(root, path), encoding="utf-8") as fh:
                title = fh.readline().lstrip("# ").strip()
        except OSError:
            title = path
        rows.append({"date": o["date"], "title": title, "trigger": o.get("trigger"), "outcome": o.get("outcome"),
                     "rule_ids": o.get("rule_ids"), "before": o.get("before"), "after": o.get("after"), "file": path})
    return {"decisions": sorted(rows, key=lambda r: r["date"], reverse=True)}


def api_weight(root, today=None):
    import arc_weight
    cfg = coach_config.load(root)
    prof = _profile(root, cfg)
    pts = [{"date": h["date"], "weight_kg": h["weight_kg"]} for h in sorted(_health(root), key=lambda h: h["date"])
           if h.get("weight_kg")]
    if prof.get("weight_kg") and not pts:
        pass  # le poids du profil n'est pas une pesée : on ne l'ajoute pas à la courbe
    out = {"points": pts, "target_kg": prof.get("target_weight_kg"), "profile_kg": prof.get("weight_kg"),
           "locked": bool(coach_config.get(cfg, "weight_loss.medical_clearance_required", False)
                          and not coach_config.get(cfg, "weight_loss.medical_clearance_confirmed", False))}
    if pts:
        out["trend"] = arc_weight.weight_trend(pts)
    return out


def api_version(root):
    """Empreinte des fichiers de données : la page la sonde et se recharge quand elle change (rechargement dynamique)."""
    import hashlib
    h = hashlib.sha1()
    for sub_ in ("activities", "medical", "nutrition", "planning", "rapports"):
        for p in sorted(glob.glob(os.path.join(root, sub_, "*.md"))):
            try:
                st = os.stat(p)
            except OSError:
                continue
            h.update(f"{os.path.relpath(p, root)}:{st.st_mtime_ns}:{st.st_size}\n".encode())
    return {"version": h.hexdigest()[:16]}


ROUTES = {"/api/version": api_version, "/api/today": api_today, "/api/decisions": api_decisions, "/api/weight": api_weight, "/api/summary": api_summary, "/api/plan": api_plan, "/api/load": api_load,
          "/api/activities": api_activities, "/api/health": api_health, "/api/calendar": api_calendar}


def allowed_hosts():
    extra = [h.strip().lower() for h in os.environ.get("ARC_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return {"127.0.0.1", "localhost", *extra}


def make_handler(root):
    web_fonts = bool(coach_config.get(coach_config.load(root), "dashboard.web_fonts", True))
    policy = csp(web_fonts)

    class H(http.server.BaseHTTPRequestHandler):
        server_version = "arc-serve"

        def log_message(self, fmt, *args):  # silencieux
            pass

        def _send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", policy)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in allowed_hosts()

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._send(403, "hôte refusé", "text/plain; charset=utf-8")
            path = self.path.split("?", 1)[0]
            if path == "/fonts.css":
                return self._send(200, FONTS_CSS if web_fonts else "/* polices du système */\n", "text/css; charset=utf-8")
            if path in STATIC:
                name, ctype = STATIC[path]
                try:
                    with open(os.path.join(WEB, name), "rb") as fh:
                        return self._send(200, fh.read(), ctype)
                except OSError:
                    return self._send(404, "introuvable", "text/plain; charset=utf-8")
            if path in ROUTES:
                try:
                    return self._send(200, json.dumps(ROUTES[path](root), ensure_ascii=False),
                                      "application/json; charset=utf-8")
                except Exception as e:  # noqa: BLE001
                    return self._send(500, json.dumps({"error": str(e)}), "application/json; charset=utf-8")
            return self._send(404, "introuvable", "text/plain; charset=utf-8")

        def _no(self):
            self._send(405, "lecture seule", "text/plain; charset=utf-8")

        do_POST = do_PUT = do_DELETE = do_PATCH = _no  # noqa: N815

    return H


def listen_address():
    """Boucle locale par défaut ; autre adresse seulement avec hôtes autorisés ET proxy authentifiant déclarés."""
    addr = os.environ.get("ARC_LISTEN", "127.0.0.1")
    if addr not in ("127.0.0.1", "localhost"):
        if not os.environ.get("ARC_ALLOWED_HOSTS", "").strip():
            raise SystemExit("ARC_LISTEN hors boucle locale : ARC_ALLOWED_HOSTS est obligatoire")
        if os.environ.get("ARC_PROXY_AUTH") != "1":
            raise SystemExit("ARC_LISTEN hors boucle locale : exige ARC_PROXY_AUTH=1 (un proxy authentifie devant le site)")
    return addr


def serve(root=ROOT, port=8765, tries=10):
    addr = listen_address()
    for p in range(port, port + tries):
        try:
            srv = socketserver.ThreadingTCPServer((addr, p), make_handler(root))
            srv.daemon_threads = True
            srv.allow_reuse_address = True
            return srv, p
        except OSError:
            continue
    raise SystemExit(f"aucun port libre entre {port} et {port + tries - 1}")


def main(argv):
    root, port = ROOT, int(coach_config.get(coach_config.load(), "dashboard.port", 8765))
    a = argv[1:]
    while a:
        k = a.pop(0)
        if k == "--port":
            port = int(a.pop(0))
        elif k == "--workspace":
            root = os.path.abspath(a.pop(0))
    srv, p = serve(root, port)
    print(f"Tableau de bord : http://{srv.server_address[0]}:{p}/  (Ctrl-C pour arrêter)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
