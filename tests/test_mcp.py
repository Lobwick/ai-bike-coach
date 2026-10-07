"""Serveur MCP (stdlib) : protocole JSON-RPC, authentification, abus, outils, ingestion, séparation site / MCP."""
import http.client
import json
import os
import subprocess
import sys
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import arc_coach_server  # noqa: E402
import arc_mcp  # noqa: E402
from test_core import block, workspace  # noqa: E402

TOKEN = "t" * 40


def mcp_ws(git=True):
    d = workspace()
    for name in ("skills", "agents"):
        os.symlink(os.path.join(ROOT, name), os.path.join(d, name))
    with open(os.path.join(d, "AGENTS.md"), "w") as fh:
        fh.write("# Workspace\n")
    os.makedirs(os.path.join(d, "config", "sports"), exist_ok=True)
    if git:
        for c in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
            subprocess.run(["git", "-C", d, *c], check=True, capture_output=True)
    return d


class Client:
    def __init__(self, port, token=TOKEN):
        self.port, self.token, self.n = port, token, 0

    def raw(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()

    def rpc(self, method, params=None, notify=False, headers=None, token="default"):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        h = {"X-Api-Key": self.token if token == "default" else token} if token != "none" else {}
        h.update(headers or {})
        st, hd, body = self.raw("POST", "/mcp", msg, h)
        return st, (json.loads(body) if body else None)

    def call(self, _tool, **args):
        st, r = self.rpc("tools/call", {"name": _tool, "arguments": args})
        assert st == 200, (st, r)
        if "error" in r:
            return r
        return json.loads(r["result"]["content"][0]["text"]), r["result"]["isError"]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = mcp_ws()
        reg = arc_mcp.build_registry(cls.d)
        cls.reg = reg
        h = arc_mcp.make_handler(reg, TOKEN, {"127.0.0.1", "localhost"})
        cls.srv = arc_coach_server.bind(h, "127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.c = Client(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()


class TestProtocol(Base):
    def test_initialize_negotiates_version(self):
        st, r = self.c.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "ai-bike-coach")
        self.assertIn("jamais", r["result"]["instructions"])
        _, r2 = self.c.rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(r2["result"]["protocolVersion"], arc_mcp.PROTOCOLS[0])
        _, r3 = self.c.rpc("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(r3["result"]["protocolVersion"], "2024-11-05")

    def test_notification_gets_202_and_no_body(self):
        st, hd, body = self.c.raw("POST", "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"X-Api-Key": TOKEN})
        self.assertEqual((st, body), (202, b""))

    def test_batch(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        st, _, body = self.c.raw("POST", "/mcp", msgs, {"X-Api-Key": TOKEN})
        out = json.loads(body)
        self.assertEqual([m["id"] for m in out], [1, 2])

    def test_errors(self):
        self.assertEqual(self.c.rpc("nope")[1]["error"]["code"], -32601)
        st, hd, body = self.c.raw("POST", "/mcp", b"{pas du json", {"X-Api-Key": TOKEN})
        self.assertEqual(json.loads(body)["error"]["code"], -32700)
        st, hd, body = self.c.raw("POST", "/mcp", {"method": "ping"}, {"X-Api-Key": TOKEN})
        self.assertEqual(json.loads(body)["error"]["code"], -32600)

    def test_tools_list_is_well_formed(self):
        tools = self.c.rpc("tools/list")[1]["result"]["tools"]
        names = {t["name"] for t in tools}
        for n in ("list_skills", "get_skill", "get_instructions", "get_status", "read_file", "write_file", "update_session", "set_profile",
                  "check_guardrails", "build_workout", "glucose_precheck", "glucose_session", "compute_session_load", "weight_plan",
                  "ingest_activities", "ingest_health", "undo_last_change", "validate_contract", "get_zones", "fueling"):
            self.assertIn(n, names)
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["description"])
        ro = {t["name"]: t["annotations"]["readOnlyHint"] for t in tools}
        self.assertTrue(ro["read_file"] and ro["check_guardrails"])
        self.assertFalse(ro["write_file"] or ro["ingest_activities"] or ro["undo_last_change"])

    def test_prompts_expose_skills(self):
        names = {p["name"] for p in self.c.rpc("prompts/list")[1]["result"]["prompts"]}
        for s in ("loop-overrides", "today", "week", "openwearables-sync", "garmin-workout-scheduling", "nightscout-glucose"):
            self.assertIn(s, names)
        r = self.c.rpc("prompts/get", {"name": "today"})[1]["result"]
        self.assertIn("/today", r["messages"][0]["content"]["text"])
        self.assertIn("error", self.c.rpc("prompts/get", {"name": "../etc"})[1])


class TestKeepAlive(Base):
    """Un proxy (Traefik) réutilise les connexions : un refus ne doit jamais corrompre la requête suivante."""

    def test_rejection_does_not_poison_the_next_request_on_the_same_connection(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        for bad in ({"X-Api-Key": "nope"}, {}, {"X-Api-Key": TOKEN, "Origin": "https://evil.example"}, {"X-Api-Key": TOKEN, "Host": "evil.example"}):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
            h.update(bad)
            c.request("POST", "/mcp", body=body, headers=h)
            r1 = c.getresponse()
            r1.read()
            self.assertIn(r1.status, (401, 403))
            h2 = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", "X-Api-Key": TOKEN}
            c.request("POST", "/mcp", body=body, headers=h2)                       # même objet connexion : http.client rouvre si fermée
            r2 = c.getresponse()
            self.assertEqual(r2.status, 200, bad)
            self.assertEqual(json.loads(r2.read())["result"], {})

    def test_good_requests_can_share_a_connection(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", "X-Api-Key": TOKEN}
        for i in range(3):
            c.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": i, "method": "ping"}), headers=h)
            r = c.getresponse()
            self.assertEqual((r.status, json.loads(r.read())["id"]), (200, i))


class TestSecurity(Base):
    def test_health_open_get_mcp_refused(self):
        self.assertEqual(self.c.raw("GET", "/health")[0], 200)
        st, hd, _ = self.c.raw("GET", "/mcp")
        self.assertEqual((st, hd.get("Allow")), (405, "POST"))
        self.assertEqual(self.c.raw("POST", "/api/summary", {})[0], 404)
        self.assertEqual(self.c.raw("DELETE", "/mcp")[0], 405)

    def test_token_in_path(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual(self.c.raw("POST", f"/mcp/{TOKEN}", msg)[0], 200)
        self.assertEqual(self.c.raw("POST", f"/mcp/{TOKEN[:-1]}", msg)[0], 401)
        self.assertEqual(self.c.raw("POST", "/mcp/", msg)[0], 401)

    def test_token_required_and_exact(self):
        for tok in ("none", "", "x" * 40, TOKEN[:-1], TOKEN + "x"):
            self.assertEqual(self.c.rpc("ping", token=tok)[0], 401, tok)
        self.assertEqual(self.c.rpc("ping")[0], 200)
        st, _, _ = self.c.raw("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(st, 200)

    def test_foreign_host_and_origin_refused(self):
        self.assertEqual(self.c.rpc("ping", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.c.rpc("ping", headers={"Origin": "https://evil.example"})[0], 403)

    def test_size_limits(self):
        big = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + b"a" * (arc_mcp.MAX_BODY + 10) + b'"}}'
        try:
            status = self.c.raw("POST", "/mcp", big, {"X-Api-Key": TOKEN})[0]
        except (BrokenPipeError, ConnectionResetError):          # le serveur coupe sans lire un corps démesuré : refus tout aussi valable
            status = 413
        self.assertEqual(status, 413)
        self.assertEqual(self.c.raw("POST", "/mcp", b"", {"X-Api-Key": TOKEN})[0], 400)

    def test_refuses_to_start_without_a_real_token(self):
        for tok in ("", None, "court", "x" * 23):
            with self.assertRaises(SystemExit):
                arc_mcp.make_handler(self.reg, tok, {"127.0.0.1"})

    def test_internal_errors_never_leak(self):
        with mock.patch.object(arc_mcp.api, "status", side_effect=RuntimeError("/secret/chemin token=abc")):
            reg = arc_mcp.build_registry(self.d)
            out = reg.call("get_status", {})
        self.assertTrue(out["isError"])
        self.assertNotIn("secret", out["content"][0]["text"])


class TestInstructions(Base):
    def test_skills(self):
        out, err = self.c.call("list_skills")
        names = {s["name"] for s in out["skills"]}
        self.assertTrue({"loop-overrides", "openwearables-sync", "today"} <= names)
        self.assertTrue(all(s["description"] for s in out["skills"]))
        sk, err = self.c.call("get_skill", name="loop-overrides")
        self.assertFalse(err)
        self.assertIn("update_nightscout_profile", sk["instructions"])
        self.assertIn("OUTILS de ce serveur", sk["instructions"])
        for bad in ("../config/workspace", "x/../y", "", "A" * 80, "nope"):
            self.assertTrue(self.c.call("get_skill", name=bad)[1], bad)

    def test_agents_and_contract(self):
        self.assertIn("cyclo-cross", self.c.call("get_instructions", agent="coach-cx")[0]["instructions"])
        self.assertIn("arc", self.c.call("get_instructions", agent="contract")[0]["instructions"])
        self.assertTrue(self.c.call("get_instructions", agent="../x")[1])


class TestTools(Base):
    def test_calculators(self):
        w, e = self.c.call("build_workout", template="cx_opener", duration_s=2400)
        self.assertFalse(e)
        self.assertEqual((w["validation_errors"], w["targets_from"]), ([], "power"))
        self.assertEqual(w["workout_data"]["sportType"]["sportTypeKey"], "cycling")
        g, _ = self.c.call("glucose_precheck", mgdl=62, direction="Flat")
        self.assertEqual(g["category"], "hypo")
        self.assertIn("Aucune dose", " ".join(g["reminders"]))
        l, _ = self.c.call("compute_session_load", duration_s=3600, np_w=250)
        self.assertEqual((l["load"], l["load_method"]), (100.0, "power"))
        n, _ = self.c.call("compute_session_load", duration_s=3600)
        self.assertEqual((n["load"], n["load_method"]), (None, None))
        self.assertIn("power", self.c.call("get_zones")[0])
        p, _ = self.c.call("weight_plan", weight_kg=80, target_kg=75, weeks=12)
        self.assertTrue(p["within_guardrail"])
        self.assertTrue(self.c.call("build_workout", template="inconnu", duration_s=60)["error"]["code"] == -32602)

    def test_glucose_session_tool(self):
        glu = [{"glucose_mgdl": v, "direction": "Flat", "timestamp": f"2026-10-03T11:{m:02d}:00Z"}
               for m, v in ((45, 150), (50, 160), (56, 181), (59, 200))] + \
              [{"glucose_mgdl": 60, "direction": "FortyFiveDown", "timestamp": "2026-10-03T12:40:00Z"}]
        s, _ = self.c.call("glucose_session", start="2026-10-03T11:55:00Z", end="2026-10-03T12:20:00Z", glucose=glu)
        self.assertEqual((s["glucose_start_mgdl"], s["hypo_events"]), (160, 1))   # dernière lecture AVANT 11:55

    def test_argument_validation(self):
        self.assertEqual(self.c.call("read_file")["error"]["code"], -32602)                 # champ obligatoire
        self.assertEqual(self.c.call("read_file", path=5)["error"]["code"], -32602)         # mauvais type
        self.assertEqual(self.c.call("read_file", path="x", extra=1)["error"]["code"], -32602)
        self.assertEqual(self.c.call("nope")["error"]["code"], -32602)
        self.assertEqual(self.c.call("ingest_activities", workouts="oui")["error"]["code"], -32602)

    def test_file_tools_keep_the_allowlist(self):
        for path in ("../config/workspace.toml", "config/workspace.toml", "/etc/passwd"):
            self.assertTrue(self.c.call("read_file", path=path)[1], path)
        bad, err = self.c.call("write_file", path="planning/x.md", content="# t\n\n```arc\n{\"type\":\"nope\"}\n```\n")
        self.assertFalse(err)
        self.assertFalse(bad["ok"])
        self.assertTrue(self.c.call("update_session", week_start="../x", date="2026-10-14", changes={"note": "a"})[1])
        self.assertTrue(self.c.call("set_profile", key="medical_clearance_confirmed", value=True)[1])
        v, _ = self.c.call("validate_contract", content="# T\n\nrien\n")
        self.assertFalse(v["ok"])


class TestIngest(Base):
    WORKOUTS = [{"id": "a1", "type": "cycling", "start_datetime": "2026-10-05T10:00:00+00:00", "end_datetime": "2026-10-05T11:00:00+00:00",
                 "duration_seconds": 3600, "distance_meters": 30000, "avg_heart_rate_bpm": 150, "max_heart_rate_bpm": 175,
                 "elevation_gain_meters": 100, "source": "strava", "intrus": "ignoré"}]
    POWER = [{"timestamp": f"2026-10-05T10:{m:02d}:00Z", "type": "power", "value": 200, "unit": "watts", "source": "strava"} for m in range(60)]

    def test_ingest_dry_run_then_real_then_no_overwrite(self):
        dry, e = self.c.call("ingest_activities", workouts=self.WORKOUTS, power=self.POWER, dry_run=True)
        self.assertFalse(e)
        self.assertEqual((dry["summary"]["written"], dry["summary"]["dry_run"]), (1, True))
        self.assertFalse(os.path.exists(os.path.join(self.d, "activities", "2026-10-05_route.md")))
        real, _ = self.c.call("ingest_activities", workouts=self.WORKOUTS, power=self.POWER)
        self.assertEqual(real["written"][0]["method"], "power")
        self.assertTrue(real["commit"])
        msg = subprocess.run(["git", "-C", self.d, "log", "-1", "--format=%s"], capture_output=True, text=True).stdout
        self.assertTrue(msg.startswith("[mobile]"))
        again, _ = self.c.call("ingest_activities", workouts=self.WORKOUTS, power=self.POWER)
        self.assertEqual((again["summary"]["written"], len(again["skipped_existing"])), (0, 1))

    def test_ingest_health(self):
        daily = [{"timestamp": "2026-10-05T05:00:00Z", "type": "resting_heart_rate", "value": 47, "unit": "bpm", "source": "whoop"}]
        h, e = self.c.call("ingest_health", daily=daily, sleep=[{"date": "2026-10-05", "duration_minutes": 450, "source": "whoop"}])
        self.assertFalse(e)
        self.assertEqual(h["written"], ["2026-10-05"])
        text = open(os.path.join(self.d, "medical", "2026-10-05_health.md")).read()
        self.assertNotIn("verdict", text.split("```")[1])


class TestRateLimit(unittest.TestCase):
    def test_writes_are_throttled(self):
        d = mcp_ws()
        reg = arc_mcp.build_registry(d)
        ok = 0
        for i in range(arc_mcp.WRITES_PER_5MIN + 5):
            r = reg.call("set_profile", {"key": "ftp_w", "value": 240 + (i % 5)})
            ok += 0 if r["isError"] else 1
        self.assertLessEqual(ok, arc_mcp.WRITES_PER_5MIN)
        self.assertIn("trop d'écritures", reg.call("set_profile", {"key": "ftp_w", "value": 241})["content"][0]["text"])


class TestSiteAndMcpAreSeparate(unittest.TestCase):
    def test_two_ports_two_surfaces(self):
        d = mcp_ws()
        env = {"COACH_MCP_TOKEN": TOKEN}
        with mock.patch.dict(os.environ, env):
            for k in ("ARC_LISTEN", "ARC_ALLOWED_HOSTS", "ARC_PROXY_AUTH"):
                os.environ.pop(k, None)
            site, mcp = arc_coach_server.build(d, 0, 0)
        try:
            for s in (site, mcp):
                threading.Thread(target=s.serve_forever, daemon=True).start()
            sc, mc = Client(site.server_address[1]), Client(mcp.server_address[1])
            self.assertEqual(sc.raw("GET", "/api/summary")[0], 200)                      # le site sert le site…
            self.assertEqual(sc.raw("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"X-Api-Key": TOKEN})[0], 405)   # …jamais le MCP
            self.assertEqual(mc.raw("GET", "/api/summary")[0], 405)                      # le MCP ne sert pas le site
            self.assertEqual(mc.raw("GET", "/")[0], 405)
            self.assertEqual(mc.rpc("ping")[0], 200)
        finally:
            site.shutdown(), mcp.shutdown(), site.server_close(), mcp.server_close()

    def test_refuses_without_token_or_proxy_declaration(self):
        d = mcp_ws()
        with mock.patch.dict(os.environ, {"COACH_MCP_TOKEN": ""}):
            with self.assertRaises(SystemExit):
                arc_coach_server.build(d, 0, 0)
        with mock.patch.dict(os.environ, {"COACH_MCP_TOKEN": TOKEN, "ARC_LISTEN": "0.0.0.0"}):
            os.environ.pop("ARC_ALLOWED_HOSTS", None)
            with self.assertRaises(SystemExit):
                arc_coach_server.build(d, 0, 0)


if __name__ == "__main__":
    unittest.main()
