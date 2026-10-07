"""Tests du noyau déterministe (stdlib `unittest`, aucune dépendance).

    python3 -m unittest discover -s tests -v
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import arc_contract  # noqa: E402
import arc_cycling  # noqa: E402
import arc_guardrails  # noqa: E402
import arc_ow  # noqa: E402
import arc_weight  # noqa: E402
import arc_workout  # noqa: E402
import coach_config  # noqa: E402


def block(obj, title="# Titre"):
    return f"{title}\n\n```arc\n{json.dumps(obj, ensure_ascii=False)}\n```\n\nTexte libre.\n"


def workspace(profile=None, activities=(), health=()):
    d = tempfile.mkdtemp()
    for sub in ("planning", "activities", "medical", "config"):
        os.makedirs(os.path.join(d, sub))
    with open(os.path.join(d, "config", "workspace.toml"), "w") as fh:
        with open(os.path.join(ROOT, "config", "workspace.toml")) as src:
            fh.write(src.read())
    p = {"type": "athlete_profile", "ftp_w": 250, "lthr_bpm": 170, "hr_max_bpm": 190,
         "hr_rest_bpm": 50, "weight_kg": 79}
    p.update(profile or {})
    with open(os.path.join(d, "planning", "Athlete_Profile.md"), "w") as fh:
        fh.write(block(p, "# Profil"))
    for a in activities:
        with open(os.path.join(d, "activities", f"{a['date']}_{a.get('n', 0)}.md"), "w") as fh:
            fh.write(block(dict({"type": "activity"}, **{k: v for k, v in a.items() if k != "n"})))
    for h in health:
        with open(os.path.join(d, "medical", f"{h['date']}_health.md"), "w") as fh:
            fh.write(block(dict({"type": "health"}, **h)))
    return d


class TestConfig(unittest.TestCase):
    def test_defaults_and_override(self):
        cfg = coach_config.load(ROOT)
        self.assertEqual(coach_config.get(cfg, "data.source"), "openwearables")
        self.assertEqual(coach_config.get(cfg, "push.target"), "garmin")
        self.assertIn("coach-cx", coach_config.get(cfg, "agents.enabled"))

    def test_parser_subset(self):
        t = coach_config.parse_toml('[a]\nx = 1 # c\ny = "p # q"\nz = ["u", "v"]\n[a.b]\nk = true\n')
        self.assertEqual(t["a"]["x"], 1)
        self.assertEqual(t["a"]["y"], "p # q")
        self.assertEqual(t["a"]["z"], ["u", "v"])
        self.assertTrue(t["a"]["b"]["k"])


class TestOpenWearables(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "data", "ow_workouts.json")) as fh:
            self.res = arc_ow.workouts(json.load(fh))

    def test_duplicates_removed(self):
        self.assertEqual(self.res["raw_records"], 8)
        counted = [s for s in self.res["sessions"] if s["counted"]]
        self.assertEqual(len(counted), 3)

    def test_envelope_not_counted(self):
        env = [s for s in self.res["sessions"] if not s["counted"]]
        self.assertEqual(len(env), 1)
        self.assertEqual(env[0]["sources"], ["whoop"])
        self.assertEqual(len(env[0]["envelope_of"]), 2)

    def test_fields_completed_and_calories_kept(self):
        s = [x for x in self.res["sessions"] if x["date"] == "2026-10-03" and x["counted"]][0]
        self.assertEqual(s["max_hr_bpm"], 162)          # complété depuis strava
        self.assertEqual(s["calories_by_source"]["strava"], 31.19)
        self.assertEqual(s["calories_kcal"], 286)       # CALORIE_ORDER, pas strava
        self.assertNotIn("avg_pace_sec_per_km", s)

    def test_missing_stays_missing(self):
        s = [x for x in self.res["sessions"] if x["date"] == "2026-10-05"][0]
        self.assertNotIn("max_hr_bpm", s)

    def test_daily_and_sleep(self):
        d = arc_ow.daily({"records": [
            {"timestamp": "2026-10-04T07:00:00Z", "type": "resting_heart_rate", "value": 60, "source": "apple"},
            {"timestamp": "2026-10-04T22:00:00Z", "type": "resting_heart_rate", "value": 100, "source": "apple"},
            {"timestamp": "2026-10-03T09:00:00Z", "type": "weight", "value": 79, "source": "whoop"}]})
        by = {x["date"]: x for x in d["days"]}
        self.assertEqual(by["2026-10-04"]["resting_hr_bpm"], 60)
        self.assertEqual(by["2026-10-03"]["weight_kg"], 79)
        s = arc_ow.sleep({"records": [
            {"date": "2026-10-05", "duration_minutes": 400, "source": "apple"},
            {"date": "2026-10-05", "duration_minutes": 450, "source": "garmin"}]})
        self.assertEqual(s["nights"][0]["source"], "garmin")


class TestLoad(unittest.TestCase):
    def test_power_load_one_hour_at_ftp_is_100(self):
        load, m = arc_cycling.session_load(3600, {"ftp_w": 250}, np_w=250)
        self.assertEqual((load, m), (100.0, "power"))

    def test_hr_load_one_hour_at_lthr_is_100(self):
        p = {"hr_rest_bpm": 50, "hr_max_bpm": 190, "lthr_bpm": 170}
        load, m = arc_cycling.session_load(3600, p, avg_hr=170)
        self.assertEqual(m, "hr")
        self.assertAlmostEqual(load, 100.0, places=0)

    def test_no_data_means_no_load(self):
        self.assertEqual(arc_cycling.session_load(3600, {}), (None, None))
        self.assertEqual(arc_cycling.session_load(3600, {"hr_rest_bpm": 50}, avg_hr=140), (None, None))

    def test_rpe_fallback(self):
        self.assertEqual(arc_cycling.session_load(3600, {}, rpe=8), (100.0, "rpe"))

    def test_series_constant_load_converges(self):
        d0 = dt.date(2026, 1, 1)
        daily = {(d0 + dt.timedelta(days=i)).isoformat(): 60.0 for i in range(300)}
        s = arc_cycling.series(daily, d0, d0 + dt.timedelta(days=299))
        self.assertAlmostEqual(s[-1]["condition"], 60.0, delta=0.5)
        self.assertAlmostEqual(s[-1]["form"], 0.0, delta=0.5)

    def test_state_from_files(self):
        today = dt.date(2026, 10, 6)
        acts = [{"date": (today - dt.timedelta(days=i)).isoformat(), "discipline": "route",
                 "duration_s": 3600, "np_w": 200} for i in range(1, 60)]
        d = workspace(activities=acts)
        st = arc_cycling.current_state(d, today, 30)
        self.assertTrue(st["reliable"])
        self.assertGreater(st["state"]["condition"], 0)

    def test_zones(self):
        z = arc_cycling.power_zones(250)
        self.assertEqual(z[3]["low_w"], round(.91 * 250))
        self.assertIsNone(z[-1]["high_w"])


class TestContract(unittest.TestCase):
    def test_valid_activity(self):
        self.assertEqual(arc_contract.validate_obj(
            {"type": "activity", "date": "2026-10-05", "discipline": "route", "duration_s": 3600}), [])

    def test_zero_and_null_rejected(self):
        e = arc_contract.validate_obj({"type": "activity", "date": "2026-10-05",
                                       "discipline": "route", "duration_s": 3600,
                                       "avg_hr_bpm": 0, "np_w": None})
        self.assertEqual(len(e), 2)

    def test_week_validation(self):
        w = {"type": "week", "week_start": "2026-10-12", "sessions": [
            {"date": "2026-10-13", "discipline": "route", "title": "x"},
            {"date": "2026-10-20", "discipline": "route", "title": "y"}]}
        e = arc_contract.validate_obj(w)
        self.assertEqual(len(e), 1)
        self.assertIn("hors de la semaine", e[0])
        w["week_start"] = "2026-10-13"
        self.assertTrue(any("lundi" in x for x in arc_contract.validate_obj(w)))

    def test_unknown_discipline(self):
        e = arc_contract.validate_obj({"type": "activity", "date": "2026-10-05",
                                       "discipline": "trail", "duration_s": 10})
        self.assertEqual(len(e), 1)


class TestGuardrails(unittest.TestCase):
    TODAY = dt.date(2026, 10, 5)

    def history(self, load_np=180):
        return [{"date": (self.TODAY - dt.timedelta(days=i)).isoformat(), "discipline": "route",
                 "duration_s": 3600, "np_w": load_np} for i in range(1, 90)]

    def week(self, sessions, **kw):
        return dict({"week_start": "2026-10-05", "sessions": sessions}, **kw)

    def test_insufficient_history_is_info(self):
        d = workspace()
        r = arc_guardrails.check(self.week([]), d, self.TODAY)
        self.assertTrue(r["ok"])
        self.assertEqual(r["violations"][0]["severity"], "info")

    def test_consecutive_hard_days(self):
        d = workspace(activities=self.history())
        s = [{"date": f"2026-10-0{n}", "discipline": "route", "title": "x",
              "duration_s": 3600, "intensity": "vo2max"} for n in (5, 6, 7)]
        r = arc_guardrails.check(self.week(s), d, self.TODAY)
        self.assertIn("R3", [v["rule"] for v in r["violations"]])

    def test_weekly_jump(self):
        d = workspace(activities=self.history())
        s = [{"date": f"2026-10-{n:02d}", "discipline": "route", "title": "x",
              "duration_s": 14400, "intensity": "endurance"} for n in (5, 7, 9, 11)]
        r = arc_guardrails.check(self.week(s), d, self.TODAY)
        self.assertIn("R2", [v["rule"] for v in r["violations"]])

    def test_quality_after_red_blocks(self):
        d = workspace(activities=self.history(),
                      health=[{"date": "2026-10-04", "verdict": "red"}])
        s = [{"date": "2026-10-05", "discipline": "route", "title": "x",
              "duration_s": 3600, "intensity": "threshold"}]
        r = arc_guardrails.check(self.week(s), d, self.TODAY)
        self.assertFalse(r["ok"])
        self.assertIn("R5", [v["rule"] for v in r["violations"]])

    def test_easy_after_red_is_fine(self):
        d = workspace(activities=self.history(),
                      health=[{"date": "2026-10-04", "verdict": "red"}])
        s = [{"date": "2026-10-05", "discipline": "route", "title": "x",
              "duration_s": 3600, "intensity": "recovery"}]
        self.assertTrue(arc_guardrails.check(self.week(s), d, self.TODAY)["ok"])

    def test_deficit_on_key_day_and_weight_rate(self):
        d = workspace(activities=self.history())
        s = [{"date": "2026-10-10", "discipline": "route", "title": "sortie longue",
              "duration_s": 14400, "intensity": "endurance"}]
        r = arc_guardrails.check(self.week(s, deficit_kcal_by_date={"2026-10-10": 600}),
                                 d, self.TODAY, weight_trend_pct=-1.4)
        rules = [v["rule"] for v in r["violations"]]
        self.assertIn("R7", rules)
        self.assertIn("R6", rules)


class TestWeight(unittest.TestCase):
    def test_plan_flags_too_fast(self):
        cfg = coach_config.load(ROOT)
        p = arc_weight.plan(80, 70, 6, cfg)
        self.assertFalse(p["within_guardrail"])
        self.assertIn("suggestion", p)
        self.assertTrue(arc_weight.plan(80, 75, 12, cfg)["within_guardrail"])

    def test_trend_without_data(self):
        self.assertIn("error", arc_weight.weight_trend([{"date": "2026-10-01"}]))

    def test_trend(self):
        t = arc_weight.weight_trend([{"date": f"2026-10-{d:02d}", "weight_kg": 80 - d * 0.1}
                                     for d in range(1, 20)])
        self.assertLess(t["trend_kg_per_week"], 0)

    def test_fueling_scales_with_duration(self):
        a = arc_weight.fueling(1800, "endurance")
        b = arc_weight.fueling(14400, "tempo")
        self.assertEqual(a["carbs_g_per_h"]["high"], 0)
        self.assertGreater(b["carbs_g_per_h"]["high"], 60)

    def test_energy_availability(self):
        self.assertEqual(arc_weight.energy_availability(1800, 900, 60)["status"], "critique")

    def test_bmr(self):
        self.assertEqual(round(arc_weight.bmr_mifflin(80, 180, 35, "m")), 1755)


class TestWorkout(unittest.TestCase):
    def test_all_templates_validate(self):
        for n in arc_workout.TEMPLATES:
            for ftp, lthr in ((250, 170), (None, 170), (None, None)):
                spec = arc_workout.template(n, 3600, ftp, lthr)
                dto = arc_workout.build(spec)
                self.assertEqual(arc_workout.validate(dto), [], (n, ftp, lthr))
                self.assertEqual(dto["sportType"]["sportTypeKey"], "cycling")

    def test_no_target_without_profile(self):
        dto = arc_workout.build(arc_workout.template("threshold", 3600))
        flat = json.dumps(dto)
        self.assertNotIn("power.zone", flat)
        self.assertNotIn("heart.rate.zone", flat)

    def test_power_targets_from_ftp(self):
        dto = arc_workout.build(arc_workout.template("threshold", 3600, 250))
        flat = json.dumps(dto)
        self.assertIn("power.zone", flat)
        self.assertNotIn('"conditionValue"', flat)

    def test_inverted_target_rejected(self):
        with self.assertRaises(ValueError):
            arc_workout.build({"name": "x", "steps": [
                {"kind": "interval", "duration_s": 60, "power_w": [300, 200]}]})


if __name__ == "__main__":
    unittest.main()
