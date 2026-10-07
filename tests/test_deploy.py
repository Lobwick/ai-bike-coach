"""Paquet de déploiement Freebox : verrous statiques (aucun secret, aucun port publié, authentification, données hors image)."""
import ast
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

    def test_image_is_dependency_free(self):
        docker = "\n".join(l for l in rd(D, "Dockerfile").splitlines() if not l.lstrip().startswith("#"))   # commentaires exclus
        self.assertNotIn("pip install", docker)                 # bibliothèque standard seulement : ~27 Mo en marche
        self.assertNotIn("fastmcp", docker.lower())
        self.assertIn("skills/", docker)                        # tous les skills sont servis par le MCP
        self.assertFalse(os.path.exists(os.path.join(D, "mcp_app.py")))

    def test_compose_has_no_secret_no_published_port(self):
        c = rd(D, "compose.yaml")
        self.assertNotRegex(c, r"(?m)^\s*ports:", "aucun port publié : tout passe par Traefik")
        self.assertIsNone(re.search(r"\b[0-9a-f]{32,}\b", c), "pas de jeton en dur")
        self.assertIn("${COACH_MCP_TOKEN}", c)
        self.assertIn("${COACH_BASIC_AUTH}", c)
        for hard in ("sk-", "password", "passwd"):
            self.assertNotIn(hard, c.lower())

    def test_one_container_two_routes_each_authenticated_differently(self):
        c = rd(D, "compose.yaml")
        self.assertEqual(len(re.findall(r"(?m)^  [a-z-]+:\s*$", c.split("services:")[1])), 1)      # un seul service
        self.assertIn("coach-site.middlewares=coach-slash,coach-auth,coach-strip", c)
        self.assertIn("basicauth.users=${COACH_BASIC_AUTH}", c)
        self.assertFalse([l for l in c.splitlines() if "coach-mcp" in l and "basicauth" in l])      # le MCP n'a pas de basicAuth…
        self.assertIn("coach-site.loadbalancer.server.port=8000", c)
        self.assertIn("coach-mcp.loadbalancer.server.port=8001", c)                                # …mais son propre port, sans le site
        self.assertIn("coach-site.service=coach-site", c)
        self.assertIn("coach-mcp.service=coach-mcp", c)

    def test_server_is_fail_closed(self):
        mcp = rd(ROOT, "scripts", "arc_mcp.py")
        self.assertIn('len(token or "") < 24', mcp)
        self.assertIn("raise SystemExit", mcp)
        self.assertIn("hmac.compare_digest", mcp)
        self.assertNotIn("allow_origins", mcp)                                                      # pas de CORS ouvert
        self.assertIn('self.headers.get("Origin")', mcp)
        serve = rd(ROOT, "scripts", "arc_serve.py")
        self.assertIn("ARC_PROXY_AUTH", serve)
        self.assertIn("ARC_ALLOWED_HOSTS", serve)

    def test_container_is_hardened(self):
        c = rd(D, "compose.yaml")
        for needle in ("cap_drop: [ALL]", "no-new-privileges:true", "read_only: true", "mem_limit: 96m"):
            self.assertEqual(c.count(needle), 1, needle)
        self.assertIn("ARC_PROXY_AUTH", c)
        self.assertIn("ARC_ALLOWED_HOSTS", c)

    def test_env_example_has_no_values_and_env_is_ignored(self):
        e = rd(D, ".env.example")
        self.assertRegex(e, r"(?m)^COACH_MCP_TOKEN=$")
        self.assertRegex(e, r"(?m)^COACH_BASIC_AUTH=''$")
        self.assertIn("deploy/freebox/.env", rd(ROOT, ".gitignore"))

    def test_migration_is_dry_run_by_default_and_never_deletes(self):
        s = rd(D, "migrate-from-mac.sh")
        code = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))
        self.assertIn("--dry-run", code)
        self.assertIn("--yes", code)
        self.assertNotRegex(code, r"--delete")
        self.assertNotRegex(code, r"\brm\s+-")

    def test_mcp_server_cannot_execute_or_delete(self):
        tree = ast.parse(rd(ROOT, "scripts", "arc_mcp.py"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
                  {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        for forbidden in ("subprocess", "shutil", "pathlib", "socket"):
            self.assertNotIn(forbidden, imports, forbidden)
        for forbidden in ("system", "popen", "rmtree", "rmdir", "eval", "exec", "remove"):
            self.assertNotIn(forbidden, names, forbidden)
        tools = re.findall(r'R\.tool\("(\w+)"', rd(ROOT, "scripts", "arc_mcp.py"))
        self.assertGreaterEqual(len(tools), 20)
        for t in tools:
            self.assertFalse(re.search(r"delete|remove|exec|garmin_push|log_treatment", t), t)     # aucun outil destructif ni d'écriture externe

    def test_bundle_is_documented_with_memory_and_garmin_caveats(self):
        r = rd(D, "README.md")
        for needle in ("27 Mo", "jamais", "garmin_push", "sans aucune authentification", "prérequis mémoire"):
            self.assertIn(needle, r.replace("JAMAIS", "jamais"), needle)


class TestNoPersonalInfraInPublicRepo(unittest.TestCase):
    def test_no_hostname_ip_or_user_in_deploy_files(self):
        for name in ("README.md", ".env.example", "compose.yaml", "migrate-from-mac.sh", "Dockerfile"):
            text = rd(D, name)
            for needle in ("lobwick", "192.168.", "felix@", "/home/felix"):
                self.assertNotIn(needle, text, f"{name}: {needle}")


if __name__ == "__main__":
    unittest.main()
