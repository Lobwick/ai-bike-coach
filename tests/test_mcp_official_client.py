"""Compatibilité avec le client MCP OFFICIEL (SDK Python `mcp`). Ignoré si le SDK n'est pas installé (Python ≥ 3.10 requis).

    uv venv --python 3.13 /tmp/v && uv pip install --python /tmp/v/bin/python "mcp>=1.20" && PYTHONPATH=. /tmp/v/bin/python -m unittest tests.test_mcp_official_client -v
"""
import asyncio
import json
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    HAVE_SDK = True
except Exception:  # noqa: BLE001
    HAVE_SDK = False

import arc_coach_server  # noqa: E402
import arc_mcp  # noqa: E402
from test_mcp import TOKEN, mcp_ws  # noqa: E402


@unittest.skipUnless(HAVE_SDK, "SDK MCP officiel absent (pip install mcp, Python ≥ 3.10)")
class TestOfficialClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = mcp_ws()
        h = arc_mcp.make_handler(arc_mcp.build_registry(cls.d), TOKEN, {"127.0.0.1", "localhost"})
        cls.srv = arc_coach_server.bind(h, "127.0.0.1", 0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def run_session(self, fn, token=TOKEN):
        async def go():
            async with streamablehttp_client(self.url, headers={"X-Api-Key": token}) as (r, w, _):
                async with ClientSession(r, w) as s:
                    init = await s.initialize()
                    return await fn(s, init)
        return asyncio.run(go())

    def test_full_session(self):
        async def fn(s, init):
            tools = await s.list_tools()
            names = {t.name for t in tools.tools}
            skills = json.loads((await s.call_tool("list_skills", {})).content[0].text)
            sk = await s.call_tool("get_skill", {"name": "today"})
            prompts = await s.list_prompts()
            pr = await s.get_prompt("week", {})
            bw = await s.call_tool("build_workout", {"template": "threshold", "duration_s": 3600})
            bad = await s.call_tool("get_skill", {"name": "../x"})
            return init, names, skills, sk, prompts, pr, bw, bad
        init, names, skills, sk, prompts, pr, bw, bad = self.run_session(fn)
        self.assertEqual(init.serverInfo.name, "ai-bike-coach")
        self.assertIn("get_skill", names)
        self.assertTrue(any(s["name"] == "loop-overrides" for s in skills["skills"]))
        self.assertFalse(sk.isError)
        self.assertIn("/today", sk.content[0].text)
        self.assertTrue(any(p.name == "today" for p in prompts.prompts))
        self.assertIn("/week", pr.messages[0].content.text)
        self.assertEqual(json.loads(bw.content[0].text)["validation_errors"], [])
        self.assertTrue(bad.isError)

    def test_wrong_token_is_rejected(self):
        with self.assertRaises(BaseException):
            self.run_session(lambda s, i: asyncio.sleep(0), token="x" * 40)


if __name__ == "__main__":
    unittest.main()
