"""Rattrapage d'historique Open Wearables : séances (puissance > FC), santé, aucune écrasement, anomalies ignorées."""
import datetime as dt
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import arc_contract  # noqa: E402
import arc_cycling  # noqa: E402
import arc_sync  # noqa: E402
from test_core import workspace  # noqa: E402


def w(i, start, dur, dist=None, hr=None, typ="cycling", src="strava", elev=None):
    s = dt.datetime.fromisoformat(start)
    return {"id": i, "type": typ, "start_datetime": start, "end_datetime": (s + dt.timedelta(seconds=dur)).isoformat(),
            "duration_seconds": dur, "distance_meters": dist, "calories_kcal": None, "avg_heart_rate_bpm": hr,
            "max_heart_rate_bpm": hr + 20 if hr else None, "elevation_gain_meters": elev, "source": src}


def power_series(start, minutes, watts):
    s = dt.datetime.fromisoformat(start)
    return [{"timestamp": (s + dt.timedelta(minutes=m)).isoformat(), "type": "power", "value": watts, "unit": "watts", "source": "strava"}
            for m in range(minutes)]


WORKOUTS = {"records": [
    w("a", "2026-10-05T10:00:00+00:00", 3600, 30000, 150, elev=120),                                   # avec puissance
    w("b", "2026-10-06T10:00:00+00:00", 3600, 28000, 150),                                             # FC seulement
    w("c", "2026-10-07T10:00:00+00:00", 3000, 20000),                                                  # rien : ni FC ni puissance
    w("d", "2026-10-05T10:00:00+00:00", 3598, None, 148, src="apple"),                                 # doublon de « a »
    w("e", "2026-10-04T10:00:00+00:00", 3600, 4000, 90, typ="walking"),                                # hors vélo
    w("f", "2026-10-03T06:00:00+00:00", 14 * 3600, 20000, 100),                                        # enregistrement oublié
    w("g", "2026-10-02T06:00:00+00:00", 200, 1000, 120),                                               # trop court
]}
POWER = {"records": power_series("2026-10-05T10:00:00+00:00", 60, 200)}


class TestActivities(unittest.TestCase):
    def setUp(self):
        self.d = workspace()                      # profil : FTP 250, FC repos 50, FC max 190
        self.r = arc_sync.sync_activities(WORKOUTS, POWER, self.d)

    def test_counts_and_ignored_reasons(self):
        self.assertEqual(self.r["summary"]["written"], 3)
        why = " | ".join(x["why"] for x in self.r["ignored"])
        for needle in ("hors vélo", "oublié", "5 min"):
            self.assertIn(needle, why)

    def test_power_beats_heart_rate_and_load_is_correct(self):
        acts = {a["date"]: a for a in arc_cycling.read_activities(self.d)}
        a = acts["2026-10-05"]
        self.assertEqual(a["load_method"], "power")
        self.assertEqual(a["avg_power_w"], 200)
        self.assertAlmostEqual(a["load"], round(100 * 1.0 * (200 / 250) ** 2, 1), places=1)   # 1 h à 80 % FTP
        self.assertEqual(a["intensity"], "tempo")
        self.assertEqual(acts["2026-10-06"]["load_method"], "hr")

    def test_no_measure_means_no_load_never_zero(self):
        a = {x["date"]: x for x in arc_cycling.read_activities(self.d)}["2026-10-07"]
        self.assertNotIn("load", a)
        self.assertNotIn("avg_hr_bpm", a)
        self.assertEqual(len(self.r["no_load"]), 1)

    def test_duplicates_merged_and_files_valid(self):
        files = sorted(os.listdir(os.path.join(self.d, "activities")))
        self.assertEqual(len(files), 3)
        self.assertEqual(arc_contract.validate_file(os.path.join(self.d, "activities", files[0])), [])
        merged = {a["date"]: a for a in arc_cycling.read_activities(self.d)}["2026-10-05"]
        self.assertEqual(sorted(merged["sources"]), ["apple", "strava"])        # a (Strava) + d (Apple) = une seule séance

    def test_never_overwrites_and_dry_run_writes_nothing(self):
        again = arc_sync.sync_activities(WORKOUTS, POWER, self.d)
        self.assertEqual(again["summary"]["written"], 0)
        self.assertEqual(len(again["skipped_existing"]), 3)
        d2 = workspace()
        arc_sync.sync_activities(WORKOUTS, POWER, d2, dry_run=True)
        self.assertEqual(os.listdir(os.path.join(d2, "activities")), [])

    def test_partial_power_coverage_falls_back_to_hr(self):
        d = workspace()
        short = {"records": power_series("2026-10-05T10:00:00+00:00", 15, 300)}      # 15 min sur 60
        arc_sync.sync_activities({"records": [WORKOUTS["records"][0]]}, short, d)
        self.assertEqual(arc_cycling.read_activities(d)[0]["load_method"], "hr")

    def test_since_filter(self):
        d = workspace()
        r = arc_sync.sync_activities(WORKOUTS, POWER, d, since="2026-10-06")
        self.assertEqual(r["summary"]["written"], 2)


class TestHealth(unittest.TestCase):
    DAILY = {"records": [
        {"timestamp": "2026-10-05T05:00:00Z", "type": "resting_heart_rate", "value": 47, "unit": "bpm", "source": "whoop"},
        {"timestamp": "2026-10-05T22:00:00Z", "type": "resting_heart_rate", "value": 95, "unit": "bpm", "source": "whoop"},   # artefact nocturne
        {"timestamp": "2026-10-05T06:00:00Z", "type": "heart_rate_variability_rmssd", "value": 66.4, "unit": "ms", "source": "whoop"},
        {"timestamp": "2026-10-05T06:00:00Z", "type": "heart_rate_variability_sdnn", "value": 80.0, "unit": "ms", "source": "apple"},  # autre métrique
        {"timestamp": "2026-10-05T06:00:00Z", "type": "heart_rate", "value": 120, "unit": "bpm", "source": "apple"},
        {"timestamp": "2026-10-06T06:00:00Z", "type": "heart_rate", "value": 130, "unit": "bpm", "source": "apple"},               # jour sans mesure santé
    ]}
    SLEEP = {"records": [{"date": "2026-10-05", "duration_minutes": 450, "source": "whoop"}]}

    def test_health_files_without_verdict_and_without_artifacts(self):
        d = workspace()
        r = arc_sync.sync_health(self.DAILY, self.SLEEP, d)
        self.assertEqual(r["written"], ["2026-10-05"])
        self.assertEqual(r["days_without_data"], 1)
        h = arc_contract.extract(open(os.path.join(d, "medical", "2026-10-05_health.md")).read())
        self.assertEqual((h["resting_hr_bpm"], h["hrv_rmssd_ms"], h["sleep_min"]), (47, 66.4, 450))
        self.assertNotIn("verdict", h)                       # le verdict est rendu par le bilan matinal, jamais déduit ici
        self.assertNotIn("hrv_sdnn_ms", h)                   # sdnn (Apple) ≠ rmssd (Whoop) : jamais mélangés
        self.assertEqual(arc_contract.validate_file(os.path.join(d, "medical", "2026-10-05_health.md")), [])

    def test_never_overwrites_health(self):
        d = workspace()
        arc_sync.sync_health(self.DAILY, self.SLEEP, d)
        self.assertEqual(arc_sync.sync_health(self.DAILY, self.SLEEP, d)["skipped_existing"], ["2026-10-05"])


class TestChartTrim(unittest.TestCase):
    def test_load_series_starts_at_first_session(self):
        import arc_serve
        d = workspace(activities=[{"date": (dt.date(2026, 10, 5) - dt.timedelta(days=i)).isoformat(), "discipline": "route",
                                   "duration_s": 3600, "np_w": 180} for i in range(1, 60)])
        out = arc_serve.api_load(d, dt.date(2026, 10, 5))
        self.assertGreater(out["series"][0]["load"], 0)


if __name__ == "__main__":
    unittest.main()
