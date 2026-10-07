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
        self.assertIn(b"Coach", b)
        self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", h["Content-Security-Policy"])
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_no_inline_script_or_external_resource_in_page(self):
        _, _, b = self.req("GET", "/")
        html = b.decode()
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", html)
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

    def test_js_never_uses_innerhtml(self):
        js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(bad, js)


if __name__ == "__main__":
    unittest.main()
