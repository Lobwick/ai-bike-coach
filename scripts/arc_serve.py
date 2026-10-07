#!/usr/bin/env python3
"""Tableau de bord local en LECTURE SEULE (stdlib, aucune dépendance, aucun appel réseau sortant).

    python3 scripts/arc_serve.py [--port 8765] [--workspace .]

- Écoute UNIQUEMENT sur 127.0.0.1 (l'adresse n'est pas configurable) ; si le port est pris, les 9 suivants sont essayés.
- GET seulement ; l'en-tête Host doit être localhost / 127.0.0.1 (protection contre le « DNS rebinding »).
- CSP stricte : aucun script ni style inline, aucune ressource externe ; la page affiche les données avec
  `textContent` uniquement (un fichier Markdown ne peut pas injecter de HTML).
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
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
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
    st = arc_cycling.current_state(root, today, 120, cfg)
    out = {"history_days": st["history_days"], "reliable": st["reliable"], "series": st["series"], "projection": [],
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


ROUTES = {"/api/summary": api_summary, "/api/plan": api_plan, "/api/load": api_load,
          "/api/activities": api_activities, "/api/health": api_health, "/api/calendar": api_calendar}


def make_handler(root):
    class H(http.server.BaseHTTPRequestHandler):
        server_version = "arc-serve"

        def log_message(self, fmt, *args):  # silencieux
            pass

        def _send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in ("127.0.0.1", "localhost")

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._send(403, "hôte refusé", "text/plain; charset=utf-8")
            path = self.path.split("?", 1)[0]
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


def serve(root=ROOT, port=8765, tries=10):
    for p in range(port, port + tries):
        try:
            srv = socketserver.ThreadingTCPServer(("127.0.0.1", p), make_handler(root))
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
    print(f"Tableau de bord : http://127.0.0.1:{p}/  (Ctrl-C pour arrêter)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
