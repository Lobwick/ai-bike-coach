"""Paquet de déploiement Freebox : verrous statiques (aucun secret, aucun port publié, authentification, données hors image)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "deploy", "freebox")


def rd(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return fh.read()


class TestDeployBundle(unittest.TestCase):
    def test_personal_data_never_enters_the_image(self):
        ign = rd(ROOT, ".dockerignore").split()
        for d in ("activities", "medical", "nutrition", "planning", "rapports", "resources", "config/workspace.user.toml", ".git"):
            self.assertIn(d, ign, d)
        docker = rd(D, "Dockerfile")
        for d in ("activities", "medical", "nutrition", "planning/", "rapports", "workspace.user.toml", ".env"):
            self.assertNotRegex(docker, rf"COPY[^\n]*\b{re.escape(d)}", d)

    def test_compose_has_no_secret_no_published_port(self):
        c = rd(D, "compose.yaml")
        self.assertNotRegex(c, r"(?m)^\s*ports:", "aucun port publié : tout passe par Traefik")
        self.assertIsNone(re.search(r"\b[0-9a-f]{32,}\b", c), "pas de jeton en dur")
        self.assertIn("${COACH_MCP_TOKEN}", c)
        self.assertIn("${COACH_BASIC_AUTH}", c)
        for hard in ("sk-", "password", "passwd"):
            self.assertNotIn(hard, c.lower())

    def test_site_is_behind_basic_auth_and_mcp_demands_a_token(self):
        c = rd(D, "compose.yaml")
        self.assertIn("coach-site.middlewares=coach-slash,coach-auth,coach-strip", c)
        self.assertIn("basicauth.users=${COACH_BASIC_AUTH}", c)
        mcp_labels = [l for l in c.splitlines() if "routers.coach-mcp" in l]
        self.assertTrue(mcp_labels)
        self.assertFalse([l for l in c.splitlines() if "coach-mcp" in l and "basicauth" in l])
        app = rd(D, "mcp_app.py")
        self.assertIn("len(TOKEN) < 24", app)
        self.assertIn("raise SystemExit", app)
        self.assertIn("hmac.compare_digest", app)
        self.assertNotIn('allow_origins', app)               # pas de CORS ouvert
        self.assertRegex(app, r'if path == "/health":\s+return JSONResponse\(\{"ok": True\}\)')

    def test_containers_are_hardened(self):
        c = rd(D, "compose.yaml")
        self.assertEqual(c.count("cap_drop: [ALL]"), 2)
        self.assertEqual(c.count("no-new-privileges:true"), 2)
        self.assertEqual(c.count("read_only: true"), 2)
        self.assertIn("ARC_PROXY_AUTH", c)
        self.assertIn("ARC_ALLOWED_HOSTS", c)

    def test_env_example_has_no_values_and_env_is_ignored(self):
        e = rd(D, ".env.example")
        self.assertRegex(e, r"(?m)^COACH_MCP_TOKEN=$")
        self.assertRegex(e, r"(?m)^COACH_BASIC_AUTH=''$")
        self.assertIn("deploy/freebox/.env", rd(ROOT, ".gitignore"))

    def test_migration_is_dry_run_by_default_and_never_deletes(self):
        s = rd(D, "migrate-from-mac.sh")
        code = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))      # commentaires exclus
        self.assertIn("--dry-run", code)
        self.assertIn("--yes", code)
        self.assertNotRegex(code, r"--delete")
        self.assertNotRegex(code, r"\brm\s+-")

    def test_every_tool_goes_through_the_tested_api(self):
        app = rd(D, "mcp_app.py")
        tools = re.findall(r"@mcp\.tool\s+def (\w+)", app)
        self.assertGreaterEqual(len(tools), 9)
        api_src = rd(ROOT, "scripts", "arc_files_api.py")
        for fn in ("list_files", "read_file", "write_file", "update_session", "set_profile", "check_guardrails",
                   "history", "undo_last_change", "get_instructions", "status"):
            self.assertIn(f"def {fn}(", api_src, fn)
        import ast
        tree = ast.parse(app)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in (n.names if isinstance(n, ast.Import) else [ast.alias(name=n.module or "")])}
        for forbidden in ("subprocess", "shutil", "pathlib"):
            self.assertNotIn(forbidden, imports, forbidden)         # le MCP n'exécute rien et ne touche pas aux fichiers lui-même
        for forbidden in ("system", "popen", "unlink", "rmtree", "remove", "rmdir", "eval", "exec"):
            self.assertNotIn(forbidden, names, forbidden)


if __name__ == "__main__":
    unittest.main()


class TestNoPersonalInfraInPublicRepo(unittest.TestCase):
    def test_no_hostname_ip_or_user_in_deploy_files(self):
        for name in ("README.md", ".env.example", "compose.yaml", "migrate-from-mac.sh", "mcp_app.py", "Dockerfile"):
            text = rd(D, name)
            for needle in ("lobwick", "192.168.", "felix@", "/home/felix"):
                self.assertNotIn(needle, text, f"{name}: {needle}")
