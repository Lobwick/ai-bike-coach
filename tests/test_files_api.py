"""API de fichiers (Claude mobile) : sécurité des chemins, validation avant écriture, git, rechargement dynamique."""
import datetime as dt
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import arc_files_api as api  # noqa: E402
import arc_serve  # noqa: E402
from test_core import block, workspace  # noqa: E402

WEEK = {"type": "week", "week_start": "2026-10-12", "sessions": [
    {"date": "2026-10-14", "discipline": "route", "title": "Sortie club", "duration_s": 6000, "intensity": "tempo"},
    {"date": "2026-10-15", "discipline": "cx", "title": "CX endurance", "duration_s": 3000, "intensity": "endurance"},
    {"date": "2026-10-15", "discipline": "strength", "title": "Renfo", "duration_s": 1500, "intensity": "strength"}]}


def ws(git=True):
    d = workspace()
    with open(os.path.join(d, "planning", "Semaine_2026-10-12.md"), "w") as fh:
        fh.write(block(WEEK, "# Semaine"))
    if git:
        for c in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "-A"],
                  ["commit", "-q", "-m", "init"]):
            subprocess.run(["git", "-C", d, *c], check=True, capture_output=True)
    return d


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.d = ws()

    def test_rejected_paths(self):
        bad = ["../config/workspace.toml", "/etc/passwd", "config/workspace.user.toml", "planning/../config/x.md",
               "planning\\x.md", "planning/a/b.md", "scripts/arc_cycling.py", "planning/x.py", "planning/.hidden.md",
               "planning/", "", "planning/x.md\x00", ".git/config", "planning/archive/x.md"]
        for p in bad:
            with self.assertRaises(api.ApiError, msg=p):
                api.write_file(self.d, p, "# t\n")

    def test_resources_are_read_only(self):
        os.makedirs(os.path.join(self.d, "resources"))
        open(os.path.join(self.d, "resources", "note.md"), "w").write("# n\n")
        self.assertEqual(api.read_file(self.d, "resources/note.md")["content"], "# n\n")
        with self.assertRaises(api.ApiError):
            api.write_file(self.d, "resources/note.md", "# x\n")

    def test_config_is_never_readable_or_listable(self):
        with self.assertRaises(api.ApiError):
            api.read_file(self.d, "config/workspace.toml")
        with self.assertRaises(api.ApiError):
            api.list_files(self.d, "config")

    def test_symlink_refused(self):
        target = os.path.join(self.d, "secret.md")
        open(target, "w").write("# secret\n")
        os.symlink(target, os.path.join(self.d, "planning", "link.md"))
        with self.assertRaises(api.ApiError):
            api.read_file(self.d, "planning/link.md")
        with self.assertRaises(api.ApiError):
            api.write_file(self.d, "planning/link.md", "# x\n")

    def test_size_limit(self):
        with self.assertRaises(api.ApiError):
            api.write_file(self.d, "planning/big.md", "# t\n" + "x" * (api.MAX_BYTES + 1))

    def test_list_only_markdown_files(self):
        open(os.path.join(self.d, "planning", "notes.txt"), "w").write("x")
        names = [f["path"] for f in api.list_files(self.d, "planning")["files"]]
        self.assertIn("planning/Semaine_2026-10-12.md", names)
        self.assertNotIn("planning/notes.txt", names)


class TestWrite(unittest.TestCase):
    def setUp(self):
        self.d = ws()

    def test_invalid_contract_is_not_written(self):
        r = api.write_file(self.d, "activities/2026-10-05_route.md",
                           "# Sortie\n\n```arc\n" + json.dumps({"type": "activity", "date": "2026-10-05", "discipline": "trail",
                                                               "duration_s": 3600}) + "\n```\n")
        self.assertFalse(r["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "activities", "2026-10-05_route.md")))
        self.assertEqual([f for f in os.listdir(os.path.join(self.d, "activities")) if f.startswith(".arc-")], [])

    def test_no_arc_block_is_refused(self):
        r = api.write_file(self.d, "rapports/x.md", "# Rapport\n\ntexte libre\n")
        self.assertFalse(r["ok"])

    def test_valid_write_is_committed_with_mobile_prefix(self):
        content = block({"type": "activity", "date": "2026-10-05", "discipline": "route", "duration_s": 3600}, "# Sortie")
        r = api.write_file(self.d, "activities/2026-10-05_route.md", content, "sortie du jour")
        self.assertTrue(r["ok"] and r["commit"])
        msg = subprocess.run(["git", "-C", self.d, "log", "-1", "--format=%s"], capture_output=True, text=True).stdout
        self.assertTrue(msg.startswith(api.COMMIT_PREFIX))

    def test_identical_rewrite_makes_no_commit(self):
        c = block({"type": "activity", "date": "2026-10-05", "discipline": "route", "duration_s": 3600}, "# S")
        api.write_file(self.d, "activities/a.md", c)
        self.assertIsNone(api.write_file(self.d, "activities/a.md", c)["commit"])

    def test_works_without_git(self):
        d = ws(git=False)
        c = block({"type": "activity", "date": "2026-10-05", "discipline": "route", "duration_s": 60}, "# S")
        r = api.write_file(d, "activities/a.md", c)
        self.assertTrue(r["ok"])
        self.assertIsNone(r["commit"])


class TestSessions(unittest.TestCase):
    def setUp(self):
        self.d = ws()
        self.path = os.path.join(self.d, "planning", "Semaine_2026-10-12.md")

    def test_update_duration_and_status(self):
        r = api.update_session(self.d, "2026-10-12", "2026-10-14", {"duration_s": 5400, "status": "moved"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["before"]["duration_s"], 6000)
        self.assertIn("5400", open(self.path).read())
        self.assertIn("Texte libre", open(self.path).read())      # le texte sous le bloc est conservé

    def test_cancel_via_status(self):
        self.assertTrue(api.update_session(self.d, "2026-10-12", "2026-10-14", {"status": "cancelled"})["ok"])

    def test_ambiguous_day_requires_title(self):
        with self.assertRaises(api.ApiError):
            api.update_session(self.d, "2026-10-12", "2026-10-15", {"duration_s": 2400})
        self.assertTrue(api.update_session(self.d, "2026-10-12", "2026-10-15", {"duration_s": 2400}, "renfo")["ok"])

    def test_move_outside_week_is_refused_and_file_unchanged(self):
        before = open(self.path).read()
        r = api.update_session(self.d, "2026-10-12", "2026-10-14", {"date": "2026-10-25"})
        self.assertFalse(r["ok"])
        self.assertEqual(open(self.path).read(), before)

    def test_unknown_field_and_bad_types(self):
        for ch in ({"discipline": "route"}, {"garmin_workout_id": 1}, {"duration_s": "long"}, {"key": 1}, {"status": "weird"}):
            with self.assertRaises(api.ApiError, msg=str(ch)):
                api.update_session(self.d, "2026-10-12", "2026-10-14", ch)

    def test_unknown_session_or_week(self):
        with self.assertRaises(api.ApiError):
            api.update_session(self.d, "2026-10-12", "2026-10-20", {"note": "x"})
        with self.assertRaises(api.ApiError):
            api.update_session(self.d, "2030-01-06", "2030-01-07", {"note": "x"})
        with self.assertRaises(api.ApiError):
            api.update_session(self.d, "../x", "2026-10-14", {"note": "x"})


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.d = ws()

    def test_set_valid_values(self):
        self.assertTrue(api.set_profile(self.d, "ftp_w", 245)["ok"])
        self.assertTrue(api.set_profile(self.d, "available_days", ["wed", "thu"])["ok"])
        self.assertEqual(api.set_profile(self.d, "weight_kg", 78.4)["after"], 78.4)

    def test_out_of_range_or_wrong_kind(self):
        for k, v in (("ftp_w", 5000), ("ftp_w", "fort"), ("ftp_w", True), ("sex", "x"), ("available_days", ["funday"]),
                     ("available_days", []), ("hr_max_bpm", 10)):
            with self.assertRaises(api.ApiError, msg=f"{k}={v}"):
                api.set_profile(self.d, k, v)

    def test_only_allowlisted_keys(self):
        for k in ("type", "medical_clearance_confirmed", "disciplines", "ow_user_id", "../x"):
            with self.assertRaises(api.ApiError, msg=k):
                api.set_profile(self.d, k, 1)


class TestHistoryAndUndo(unittest.TestCase):
    def test_undo_only_reverts_own_commits(self):
        d = ws()
        with self.assertRaises(api.ApiError):                       # dernier commit = « init », pas l'API
            api.undo_last_change(d)
        api.set_profile(d, "ftp_w", 250)
        before = open(os.path.join(d, "planning", "Athlete_Profile.md")).read()
        self.assertIn("250", before)
        r = api.undo_last_change(d)
        self.assertTrue(r["ok"])
        self.assertNotEqual(open(os.path.join(d, "planning", "Athlete_Profile.md")).read(), before)
        self.assertGreaterEqual(len(api.history(d)["commits"]), 3)

    def test_history_of_a_file(self):
        d = ws()
        api.set_profile(d, "ftp_w", 251)
        self.assertEqual(api.history(d, "planning/Athlete_Profile.md")["commits"][0]["message"][:8], "[mobile]")


class TestInstructionsAndGuardrails(unittest.TestCase):
    def test_instructions_come_from_code_not_data(self):
        r = api.get_instructions(ROOT, "coach-cx")
        self.assertIn("cyclo-cross", r["instructions"])
        with self.assertRaises(api.ApiError):
            api.get_instructions(ROOT, "../config/workspace")
        self.assertIn("coach-route", api.get_instructions(ROOT)["agents"])

    def test_check_guardrails_runs(self):
        d = ws()
        r = api.check_guardrails(d, "2026-10-12")
        self.assertIn("violations", r)


class TestLiveReloadAndHosting(unittest.TestCase):
    def test_version_changes_when_a_file_changes(self):
        d = ws()
        v1 = arc_serve.api_version(d)["version"]
        api.set_profile(d, "ftp_w", 260)
        self.assertNotEqual(arc_serve.api_version(d)["version"], v1)
        self.assertEqual(arc_serve.api_version(d)["version"], arc_serve.api_version(d)["version"])

    def test_loopback_default_and_fail_closed(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("ARC_LISTEN", "ARC_ALLOWED_HOSTS", "ARC_PROXY_AUTH"):
                os.environ.pop(k, None)
            self.assertEqual(arc_serve.listen_address(), "127.0.0.1")
        with mock.patch.dict(os.environ, {"ARC_LISTEN": "0.0.0.0"}, clear=False):
            os.environ.pop("ARC_ALLOWED_HOSTS", None)
            os.environ.pop("ARC_PROXY_AUTH", None)
            with self.assertRaises(SystemExit):
                arc_serve.listen_address()
        with mock.patch.dict(os.environ, {"ARC_LISTEN": "0.0.0.0", "ARC_ALLOWED_HOSTS": "a.example"}, clear=False):
            os.environ.pop("ARC_PROXY_AUTH", None)
            with self.assertRaises(SystemExit):
                arc_serve.listen_address()
        with mock.patch.dict(os.environ, {"ARC_LISTEN": "0.0.0.0", "ARC_ALLOWED_HOSTS": "a.example", "ARC_PROXY_AUTH": "1"}):
            self.assertEqual(arc_serve.listen_address(), "0.0.0.0")
            self.assertIn("a.example", arc_serve.allowed_hosts())

    def test_page_uses_relative_urls_to_work_under_a_subpath(self):
        html = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
        for attr in ('href="/', 'src="/'):
            self.assertNotIn(attr, html)
        js = open(os.path.join(ROOT, "web", "js", "app.js"), encoding="utf-8").read()
        self.assertIn('fetch(u.replace(/^\\//, ""))', js)


if __name__ == "__main__":
    unittest.main()
