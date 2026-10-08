"""Tableau de bord : API pures + serveur HTTP réel sur un port éphémère (127.0.0.1)."""
import datetime as dt
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import arc_serve  # noqa: E402
from test_core import block, workspace  # noqa: E402

TODAY = dt.date(2026, 10, 5)


def ws_with_plan(n_hist=60):
    acts = [{"date": (TODAY - dt.timedelta(days=i)).isoformat(), "discipline": "route", "duration_s": 3600,
             "np_w": 190, "load": 80.0, "load_method": "power"} for i in range(1, n_hist)]
    d = workspace(activities=acts, health=[{"date": "2026-10-04", "resting_hr_bpm": 48, "verdict": "green",
                                            "tir_pct": 74, "weight_kg": 79.0}])
    week = {"type": "week", "week_start": "2026-10-05", "sessions": [
        {"date": "2026-10-07", "discipline": "route", "title": "Club", "duration_s": 6000, "intensity": "tempo", "fixed": True},
        {"date": "2026-10-11", "discipline": "cx", "title": "Course Halluin", "duration_s": 4800, "intensity": "race",
         "race": True, "venue": "Halluin", "planned_load": 110, "alternatives": [{"date": "2026-10-10", "place": "Anzin"}]}]}
    with open(os.path.join(d, "planning", "Semaine_2026-10-05.md"), "w") as fh:
        fh.write(block(week, "# Semaine"))
    os.makedirs(os.path.join(d, "resources"))
    with open(os.path.join(d, "resources", "calendrier-cx-ufolep-2026-2027.md"), "w") as fh:
        fh.write("| Date | Jour | Lieu | Organisateur |\n|---|---|---|---|\n"
                 "| 2026-10-11 | dim | Halluin | Velo Club Union Halluin |\n| 2026-10-10 | sam | Anzin | Vc Escaut |\n"
                 "| 2026-09-01 | mar | Passé | X |\n")
    return d


class TestApi(unittest.TestCase):
    def test_summary_with_history(self):
        s = arc_serve.api_summary(ws_with_plan(), TODAY)
        self.assertTrue(s["load"]["reliable"])
        self.assertEqual(s["profile"]["ftp_w"], 250)
        self.assertEqual(s["next_race"]["venue"], "Halluin")
        self.assertEqual(s["weight_latest"]["kg"], 79.0)
        self.assertEqual(s["profile"]["w_per_kg"], round(250 / 79, 2))

    def test_summary_without_history_is_honest(self):
        s = arc_serve.api_summary(workspace(), TODAY)
        self.assertFalse(s["load"]["reliable"])
        self.assertIsNone(s["next_race"])

    def test_load_projection_only_when_reliable(self):
        d = arc_serve.api_load(ws_with_plan(), TODAY)
        self.assertTrue(d["projection"])
        self.assertTrue(all(r["date"] > TODAY.isoformat() for r in d["projection"]))
        d2 = arc_serve.api_load(workspace(), TODAY)
        self.assertEqual(d2["projection"], [])
        self.assertIn("note", d2)

    def test_plan_has_totals_and_guardrails(self):
        p = arc_serve.api_plan(ws_with_plan(), TODAY)["weeks"][0]
        self.assertGreater(p["planned_load"], 100)
        self.assertIsInstance(p["guardrails"], list)

    def test_calendar_marks_picked_and_drops_past(self):
        r = arc_serve.api_calendar(ws_with_plan(), TODAY)["races"]
        self.assertEqual([x["place"] for x in r], ["Halluin", "Anzin"])
        self.assertTrue(r[0]["picked"])
        self.assertFalse(r[1]["picked"])

    def test_activities_and_health(self):
        d = ws_with_plan()
        self.assertEqual(len(arc_serve.api_activities(d)["activities"]), 40)
        self.assertEqual(arc_serve.api_health(d)["days"][0]["tir_pct"], 74)

    def test_missing_calendar_is_a_note(self):
        self.assertIn("note", arc_serve.api_calendar(workspace(), TODAY))


class TestHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ws_with_plan()
        cls.srv, cls.port = arc_serve.serve(cls.root, 18765)
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest(method, path, skip_host=True)
        c.putheader("Host", host or f"127.0.0.1:{self.port}")
        c.endheaders()
        r = c.getresponse()
        body = r.read()
        return r.status, dict(r.getheaders()), body

    def test_binds_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_page_and_csp(self):
        st, h, b = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"ai-bike-coach", b)
        self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", h["Content-Security-Policy"])
        self.assertNotIn("unsafe-eval", h["Content-Security-Policy"])
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_all_static_files_are_served_with_right_types(self):
        for path, ctype in (("/css/app.css", "text/css"), ("/js/app.js", "text/javascript"), ("/js/chart.js", "text/javascript"),
                            ("/js/format.js", "text/javascript"), ("/js/nav.js", "text/javascript"), ("/favicon.svg", "image/svg+xml")):
            st, h, b = self.req("GET", path)
            self.assertEqual(st, 200, path)
            self.assertIn(ctype, h["Content-Type"], path)
            self.assertTrue(b, path)

    def test_every_module_import_resolves_to_a_served_file(self):
        import re
        for name in ("app.js", "chart.js", "format.js", "nav.js"):
            src = open(os.path.join(ROOT, "web", "js", name), encoding="utf-8").read()
            for rel in re.findall(r'from "\./([a-z]+\.js)"', src):
                self.assertEqual(self.req("GET", f"/js/{rel}")[0], 200, f"{name} -> {rel}")

    def test_fonts_are_the_only_external_resource_and_switchable(self):
        _, h, b = self.req("GET", "/fonts.css")
        self.assertIn(b"fonts.googleapis.com", b)
        self.assertIn("https://fonts.googleapis.com", h["Content-Security-Policy"])
        self.assertIn("font-src https://fonts.gstatic.com", h["Content-Security-Policy"])
        self.assertEqual(arc_serve.csp(False).count("http"), 0)


    def test_no_inline_script_or_external_resource_in_page(self):
        _, _, b = self.req("GET", "/")
        html = b.decode()
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", html)           # les polices passent par /fonts.css, jamais par la page
        self.assertNotRegex(html, r"<script(?![^>]*\ssrc=)")
        self.assertNotIn(" style=", html)

    def test_api_json(self):
        st, h, b = self.req("GET", "/api/summary")
        self.assertEqual(st, 200)
        self.assertIn("application/json", h["Content-Type"])
        self.assertIn("load", json.loads(b))

    def test_read_only(self):
        for m in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(self.req(m, "/api/summary")[0], 405, m)

    def test_foreign_host_refused(self):
        self.assertEqual(self.req("GET", "/api/summary", host="evil.example.com")[0], 403)
        self.assertEqual(self.req("GET", "/", host="attacker.test:80")[0], 403)

    def test_no_traversal_or_unknown_paths(self):
        for p in ("/../config/workspace.toml", "/%2e%2e/AGENTS.md", "/planning/Athlete_Profile.md", "/app.js/../../AGENTS.md"):
            self.assertEqual(self.req("GET", p)[0], 404, p)

    def test_js_never_writes_raw_html(self):
        import re
        for name in ("app.js", "chart.js", "format.js", "nav.js"):
            with open(os.path.join(ROOT, "web", "js", name), encoding="utf-8") as fh:
                code = re.sub(r"//[^\n]*|/\*.*?\*/", "", fh.read(), flags=re.S)
            for bad in (r"\.innerHTML", r"\.outerHTML", r"insertAdjacentHTML", r"document\.write", r"\beval\(", r"new Function"):
                self.assertIsNone(re.search(bad, code), f"{name}: {bad}")

    def test_template_escapes_by_default(self):
        js = open(os.path.join(ROOT, "web", "js", "app.js"), encoding="utf-8").read()
        self.assertIn("const str = (v) => (v instanceof Raw ? v.s", js)
        self.assertIn("F.esc(v)", js)


if __name__ == "__main__":
    unittest.main()


class TestJsSyntax(unittest.TestCase):
    """Un JS invalide = site blanc : on le détecte avant le déploiement (nécessite node)."""

    @unittest.skipUnless(__import__("shutil").which("node"), "node absent")
    def test_web_modules_parse(self):
        import shutil, subprocess, tempfile
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent / "web" / "js"
        for f in sorted(root.glob("*.js")):
            with tempfile.TemporaryDirectory() as d:
                m = Path(d) / (f.stem + ".mjs")
                shutil.copy(f, m)
                r = subprocess.run(["node", "--check", str(m)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{f.name}: {r.stderr}")
