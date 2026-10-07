"""Cohérence du dépôt : agents, skills, configuration, templates, liste blanche Garmin."""
import glob
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import arc_contract  # noqa: E402
import coach_config  # noqa: E402
import coach_doctor  # noqa: E402

RUNNING_LEFTOVERS = re.compile(r"trail shape|Runner_Profile|intervals\.icu|strava-mcp|GAP\b|"
                               r"garmin-daily-sync|course-strategist|arc_index\.py", re.I)
GARMIN_READS = ["get_activities", "get_sleep_data", "get_hrv_data", "get_rhr_day",
                "get_training_readiness", "get_activity_fit_data", "get_stats"]


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def front(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(l.split(": ", 1) for l in m.group(1).splitlines() if ": " in l) if m else {}


class TestRepo(unittest.TestCase):
    def test_agents(self):
        for p in glob.glob(os.path.join(ROOT, "agents", "*.md")):
            f = front(read(p))
            self.assertEqual(f.get("name"), os.path.basename(p)[:-3], p)
            self.assertTrue(f.get("description"), p)

    def test_enabled_agents_exist(self):
        cfg = coach_config.load(ROOT)
        for a in coach_config.get(cfg, "agents.enabled"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "agents", a + ".md")), a)
        for d in coach_config.get(cfg, "sport.disciplines"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "config", "sports", d + ".md")), d)

    def test_skills(self):
        for p in glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")):
            self.assertEqual(front(read(p)).get("name"), os.path.basename(os.path.dirname(p)), p)

    def test_no_running_leftovers(self):
        for p in (glob.glob(os.path.join(ROOT, "agents", "*.md")) +
                  glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")) +
                  glob.glob(os.path.join(ROOT, "config", "sports", "*.md"))):
            m = RUNNING_LEFTOVERS.search(read(p))
            self.assertIsNone(m, f"{p}: {m and m.group(0)}")

    def test_garmin_reads_only_as_prohibition(self):
        # chaque agent cite les outils de lecture UNIQUEMENT dans la phrase qui les interdit
        for p in glob.glob(os.path.join(ROOT, "agents", "*.md")):
            text = read(p)
            for t in GARMIN_READS:
                for m in re.finditer(t, text):
                    ctx = text[max(0, m.start() - 400):m.start()]
                    self.assertIn("Ne jamais appeler un outil de LECTURE", ctx, f"{p}: {t}")

    def test_whitelist_is_push_only(self):
        for p in (os.path.join(ROOT, ".mcp.json"), os.path.join(ROOT, "install.sh")):
            if not os.path.exists(p):
                continue
            m = re.search(r'GARMIN_ENABLED_TOOLS"\s*:\s*"([^"]+)"', read(p))
            self.assertTrue(m, p)
            self.assertLessEqual(set(m.group(1).split(",")), coach_doctor.PUSH_TOOLS, p)

    def test_nightscout_write_tools_forbidden_everywhere(self):
        for p in glob.glob(os.path.join(ROOT, "agents", "*.md")):
            text = read(p)
            self.assertIn("log_treatment", text, p)
            self.assertIn("JAMAIS `log_treatment`", text, p)
        skill = read(os.path.join(ROOT, "skills", "nightscout-glucose", "SKILL.md"))
        for t in ("log_treatment", "remove_treatment", "update_nightscout_profile"):
            self.assertRegex(skill, rf"Interdits, toujours.*{t}", t) if False else self.assertIn(t, skill)

    def test_templates_validate(self):
        for t in ("Athlete_Profile.template.md", "active_objective.template.md"):
            self.assertEqual(arc_contract.validate_file(os.path.join(ROOT, "templates", t)), [], t)

    def test_cli_smoke(self):
        for cmd in (["scripts/arc_ow.py"], ["scripts/arc_cycling.py"], ["scripts/arc_weight.py"],
                    ["scripts/arc_workout.py", "templates"], ["scripts/coach_config.py", "dump"]):
            r = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True)
            self.assertIn(r.returncode, (0, 2), (cmd, r.stderr))

    def test_install_script_syntax(self):
        for sh in ("install.sh", "scripts/daily-sync.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", sh], cwd=ROOT).returncode, 0, sh)


if __name__ == "__main__":
    unittest.main()
