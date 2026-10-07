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
import arc_glucose  # noqa: E402
import arc_override  # noqa: E402
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


def shared_cfg():
    """Config versionnée seule : les tests ne dépendent jamais de workspace.user.toml."""
    with open(os.path.join(ROOT, "config", "workspace.toml"), encoding="utf-8") as fh:
        return coach_config.parse_toml(fh.read())


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


class TestOpenWearablesV2(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(HERE, "data", name)) as fh:
            return json.load(fh)

    def test_activity_zero_is_missing(self):
        days = {d["date"]: d for d in arc_ow.activity(self.load("ow_activity.json"))["days"]}
        self.assertEqual(days["2026-10-05"]["total_kcal"], 3676.5)
        self.assertNotIn("steps", days["2026-10-05"])           # 0 pas = absent
        self.assertNotIn("total_kcal", days["2026-10-06"])
        self.assertTrue(days["2026-10-06"]["energy_missing"])
        self.assertEqual(days["2026-10-06"]["steps"], 9968)

    def test_hourly_energy_series_ignored_in_daily(self):
        d = arc_ow.daily({"records": [
            {"timestamp": "2026-10-04T22:00:00Z", "type": "basal_energy", "value": 3755.458, "source": "apple"},
            {"timestamp": "2026-10-04T08:00:00Z", "type": "respiratory_rate", "value": 17.754, "source": "apple"},
            {"timestamp": "2026-10-04T08:00:00Z", "type": "oxygen_saturation", "value": 95.125, "source": "apple"}]})
        row = d["days"][0] if len(d["days"]) == 1 else [x for x in d["days"] if x["date"] == "2026-10-04"][0]
        self.assertNotIn("basal_energy", row)
        self.assertEqual(row["respiratory_rate_brpm"], 17.8)
        self.assertEqual(row["spo2_pct"], 95.1)

    def test_hr_series_merges_simultaneous_samples(self):
        ser = arc_ow.hr_series(self.load("ow_hr.json"), "2026-10-05T10:10:35Z", "2026-10-05T11:57:47Z")
        self.assertEqual(ser["resolution_s"], 300)
        self.assertEqual(ser["n"], len({s["t"] for s in ser["samples"]}))   # un point par horodatage

    def test_hr_load_close_to_avg_hr_on_steady_ride_and_has_zones(self):
        ser = arc_ow.hr_series(self.load("ow_hr.json"), "2026-10-05T10:10:35Z", "2026-10-05T11:57:47Z")
        prof = {"hr_rest_bpm": 50, "hr_max_bpm": 192, "lthr_bpm": 170}
        r = arc_cycling.hr_series_load(ser["samples"], prof, 300)
        self.assertEqual(r["load_method"], "hr_series")
        avg, _ = arc_cycling.session_load(6432, prof, avg_hr=150)
        self.assertAlmostEqual(r["load"], avg, delta=10)
        self.assertGreater(sum(r["time_in_zone_min"].values()), 90)
        self.assertEqual(arc_contract.validate_obj(
            {"type": "activity", "date": "2026-10-05", "discipline": "route", "duration_s": 6432,
             "load": r["load"], "load_method": r["load_method"], "time_in_zone_min": r["time_in_zone_min"],
             "easy_share_pct": r["easy_share_pct"], "hr_drift_pct": r["hr_drift_pct"]}), [])

    def test_intervals_load_higher_than_avg_hr(self):
        # 6 × (2 min à 180 / 3 min à 100) : la FC moyenne écrase l'effort, la série le voit
        pts, t = [], dt.datetime(2026, 10, 5, 10, 0)
        for _ in range(6):
            for bpm, n in ((180, 2), (100, 3)):
                for _ in range(n):
                    pts.append({"t": t.isoformat(), "bpm": bpm}); t += dt.timedelta(minutes=1)
        prof = {"hr_rest_bpm": 50, "hr_max_bpm": 192, "lthr_bpm": 170}
        series = arc_cycling.hr_series_load(pts, prof, 60)["load"]
        avg, _ = arc_cycling.session_load(len(pts) * 60, prof, avg_hr=sum(p["bpm"] for p in pts) / len(pts))
        self.assertGreater(series, avg)

    def test_hr_load_refuses_without_profile(self):
        self.assertIsNone(arc_cycling.hr_series_load([{"t": "2026-10-05T10:00:00", "bpm": 120}] * 5, {}, 60))


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
        cfg = shared_cfg()
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


class TestGlucose(unittest.TestCase):
    def entries(self, vals, start="2026-10-06T06:00:00Z", step=5):
        t0 = arc_glucose._dt(start)
        return {"result": [{"glucose_mgdl": v, "direction": "Flat",
                            "timestamp": (t0 + dt.timedelta(minutes=step * i)).isoformat()}
                           for i, v in enumerate(vals)]}

    def test_precheck_categories(self):
        cat = lambda v, d=None: arc_glucose.precheck(v, d)["category"]  # noqa: E731
        self.assertEqual(cat(60), "hypo")
        self.assertEqual(cat(85), "bas")
        self.assertEqual(cat(104), "limite_basse")
        self.assertEqual(cat(150), "cible")
        self.assertEqual(cat(220), "haute_acceptable")
        self.assertEqual(cat(300), "haute")

    def test_precheck_never_doses(self):
        r = arc_glucose.precheck(104, "Flat")
        self.assertIn("Aucune dose", " ".join(r["reminders"]))
        self.assertIn("pas un avis médical", r["disclaimer"])

    def test_falling_trend_adds_carbs(self):
        self.assertIn("descendante", arc_glucose.precheck(140, "SingleDown")["message"])

    def test_session_detects_hypo_after(self):
        # 06:00-06:30 séance ; glycémie 110 → 95 → 68 après
        doc = self.entries([110, 108, 105, 100, 98, 95, 92, 90, 80, 68, 72, 80])
        res = arc_glucose.session(doc, "2026-10-06T06:00:00Z", "2026-10-06T06:30:00Z")
        self.assertEqual(res["glucose_start_mgdl"], 110)
        self.assertEqual(res["hypo_events"], 1)
        self.assertEqual(res["glucose_post_min_mgdl"], 68)
        self.assertTrue(any("hypoglycémies tardives" in f for f in res["flags"]))

    def test_session_treatments_carbs_and_override(self):
        doc = self.entries([100] * 12)
        tr = {"result": [
            {"eventType": "Carb Correction", "carbs": 15, "timestamp": "2026-10-06T06:10:00Z"},
            {"eventType": "Temporary Override", "reason": "sport", "duration": 60,
             "insulinNeedsScaleFactor": 0.41, "timestamp": "2026-10-06T05:50:00Z"}]}
        res = arc_glucose.session(doc, "2026-10-06T06:00:00Z", "2026-10-06T06:30:00Z", tr)
        self.assertEqual(res["carbs_logged_g"], 15)
        self.assertEqual(res["overrides"][0]["reason"], "sport")
        self.assertEqual(res["hypo_events"], 0)

    def test_missing_data_is_error_not_normal(self):
        self.assertIn("error", arc_glucose.day({"result": []}))
        self.assertIn("error", arc_glucose.session({"result": []}, "2026-10-06T06:00:00Z", "2026-10-06T06:30:00Z"))

    def test_day_stats(self):
        r = arc_glucose.day(self.entries([60, 100, 120, 200] * 40))
        self.assertEqual(r["tir_pct"], 50)
        self.assertEqual(r["time_below_pct"], 25.0)

    def test_contract_accepts_glucose_keys_and_zero_hypo(self):
        self.assertEqual(arc_contract.validate_obj(
            {"type": "activity", "date": "2026-10-05", "discipline": "route", "duration_s": 3600,
             "glucose_start_mgdl": 110, "hypo_events": 0}), [])

    def test_weight_plan_blocked_without_clearance(self):
        cfg = {"weight_loss": {"medical_clearance_required": True, "medical_clearance_confirmed": False},
               "guardrails": {}}
        p = arc_weight.plan(79, 70, 20, cfg)
        self.assertTrue(p["blocked"])
        self.assertEqual(p["average_daily_deficit_kcal"], 0)
        cfg["weight_loss"]["medical_clearance_confirmed"] = True
        self.assertNotIn("blocked", arc_weight.plan(79, 70, 20, cfg))


class TestOverride(unittest.TestCase):
    def profile(self):
        with open(os.path.join(HERE, "data", "ns_profile.json")) as fh:
            return json.load(fh)

    def test_presets_expose_nothing_sensitive(self):
        out = json.dumps(arc_override.presets(self.profile()), ensure_ascii=False)
        for secret in ("SYNTHETIC-TOKEN", "basal", "sens", "maximumBolus", "deviceToken"):
            self.assertNotIn(secret, out)
        self.assertEqual([p["name"] for p in arc_override.presets(self.profile())["presets"]],
                         ["stop", "sport", "long"])

    def test_activations_merge_duplicates_and_end(self):
        t = {"result": [
            {"eventType": "Temporary Override", "reason": "🚴‍♂️ sport", "duration": 0,
             "timestamp": "2026-10-06T06:26:00Z", "insulinNeedsScaleFactor": 0.41, "correctionRange": [150, 160]},
            {"eventType": "Temporary Override", "reason": "🚴‍♂️ sport", "duration": 22,
             "timestamp": "2026-10-06T06:26:30Z", "insulinNeedsScaleFactor": 0.41, "correctionRange": [150, 160]},
            {"eventType": "Temporary Override", "reason": "❌ stop", "duration": 60,
             "timestamp": "2026-10-06T07:00:00Z", "insulinNeedsScaleFactor": 0.1}]}
        acts = arc_override.activations(t)["activations"]
        self.assertEqual([a["name"] for a in acts], ["sport", "stop"])
        self.assertTrue(acts[0]["end"].startswith("2026-10-06T06:48"))

    def sess(self, day, hypo=False, start=120, lead_h=0):
        return {"window": {"start": f"2026-10-0{day}T08:00:00+00:00", "end": f"2026-10-0{day}T10:00:00+00:00"},
                "glucose_start_mgdl": start, "glucose_min_mgdl": 62 if hypo else 100,
                "glucose_max_mgdl": 180, "hypo_events": 1 if hypo else 0}

    def acts(self, days, minutes_before=10):
        return [{"name": "sport", "start": f"2026-10-0{d}T0{7 if minutes_before > 50 else 8}:{'00' if minutes_before > 50 else '00'}:00+00:00".replace("T08:00", "T07:50" if minutes_before == 10 else "T08:00"),
                 "end": f"2026-10-0{d}T11:00:00+00:00"} for d in days]

    def test_hypo_pattern_gives_bounded_proposal(self):
        pres = arc_override.presets(self.profile())["presets"]
        ss = [self.sess(1, True), self.sess(2, True), self.sess(3, False)]
        acts = self.acts([1, 2, 3])
        r = arc_override.analyze(ss, acts, pres)
        p = [x for x in r["proposals"] if x["override"] == "sport"][0]
        self.assertEqual(p["kind"], "moins_agressif")
        self.assertEqual(p["status"], "hypothèse")
        sc = p["proposal"]["insulin_scale"]
        self.assertAlmostEqual(sc["current"] - sc["candidate"], arc_override.STEP_SCALE, places=2)
        t = p["proposal"]["target_range_mgdl"]
        self.assertEqual([b - a for a, b in zip(t["current"], t["candidate"])], [10, 10])
        self.assertIn("long", r["unused_presets"])
        self.assertIn("Loop", r["how_to_apply"])

    def test_insufficient_data_gives_no_numbers(self):
        pres = arc_override.presets(self.profile())["presets"]
        r = arc_override.analyze([self.sess(1, True), self.sess(2, True)], self.acts([1, 2]), pres)
        self.assertEqual(r["proposals"][0]["kind"], "insuffisant")

    def test_no_override_hypos_suggest_creating_one(self):
        pres = arc_override.presets(self.profile())["presets"]
        ss = [self.sess(d, True, start=80) for d in (1, 2, 3)]
        r = arc_override.analyze(ss, [], pres)
        self.assertEqual(r["proposals"][0]["kind"], "creer_ou_utiliser")
        self.assertIn("copie", r["proposals"][0]["proposal"])

    def test_scale_never_leaves_bounds(self):
        pres = [{"name": "x", "insulin_scale": 0.05, "target_range_mgdl": [150, 160]}]
        acts = [{"name": "x", "start": f"2026-10-0{d}T07:00:00+00:00", "end": f"2026-10-0{d}T11:00:00+00:00"} for d in (1, 2, 3)]
        r = arc_override.analyze([self.sess(d, True) for d in (1, 2, 3)], acts, pres)
        self.assertGreaterEqual(r["proposals"][0]["proposal"]["insulin_scale"]["candidate"], 0.05)


if __name__ == "__main__":
    unittest.main()
