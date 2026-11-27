from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from s1.game import new_game, open_turn, scout_notice
from s1.pilot import config_for, play, verify_client, verify_smoke
from s1.table import ALLOWED, game_call, prepare, release, serve, snapshot
from w1.gateway import MODEL, translate


class LeagueHarnessTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.run = self.root / "league"
        self.run.mkdir()
        (self.run / "trace").mkdir()
        self.directory = self.run / "arena"
        state = new_game("A", 31)
        prepare(self.run, state)
        open_turn(state, 1)
        release(self.run, 1, state)

    def test_schema_rejection_idempotence_and_window(self):
        query = {"model":MODEL, "max_tokens":64, "messages":[],
                 "tools":[{"name": "mcp__table__act", "input_schema": {"type":"object"}}]}
        self.assertIn("tools", translate(query, {}, ALLOWED))
        with self.assertRaises(ValueError):
            translate(query, {})
        query["tools"][0]["name"] = "mcp__office__shell"
        with self.assertRaises(ValueError):
            translate(query, {}, ALLOWED)

        def call(number, name, args):
            return game_call(self.directory, 1, name, args, "rpc", number)
        note = {"action":{"op":"note","text":"remember"}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(call, 1, "act", note) for _ in range(2)]
            self.assertTrue(all(f.result()["ok"] for f in calls))
        self.assertFalse(call(1, "act", {"action":{"op":"note","text":"other"}})["ok"])
        self.assertFalse(call(2, "readFile", {"path":"../snapshots/1.json"})["ok"])
        self.assertFalse(call(3, "act", {"action":{"op":"pay"}, "turn":8})["ok"])
        self.assertFalse(call(4, "act", {"action":{"op":"read","path":"../manifest.json"}})["ok"])
        self.assertEqual(call(5, "act", {"action":{"op":"read_note"}})["note"], "remember")
        snapshot(self.run, 1)
        self.assertFalse(call(6, "act", note)["ok"])
        rows = [json.loads(line) for line in (self.run / "trace/tools-1.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["n"] for r in rows], list(range(1, 6)))

    def test_stdio_scope_and_docker_mount(self):
        requests = [{"id":7,"method":"tools/list"}, {"id":8,"method":"resources/list"},
                    {"id":9,"method":"tools/call","params":{"name":"observe","arguments":{}}},
                    {"id":10,"method":"tools/call","params":{"name":"read","arguments":{"path":"/etc/passwd"}}}]
        out = StringIO()
        serve(self.directory, 1, StringIO("\n".join(map(json.dumps, requests))), out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual({t["name"] for t in responses[0]["result"]["tools"]}, {"act", "observe"})
        self.assertEqual(responses[1]["error"]["code"], -32601)
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertTrue(responses[3]["result"]["isError"])
        self.assertNotIn(str(self.run), out.getvalue())
        cfg = config_for(self.run, 1, "sha256:fixed")["mcpServers"]["table"]
        self.assertEqual(cfg["command"], "docker")
        self.assertEqual(cfg["args"].count("--mount"), 1)
        self.assertIn("--network=none", cfg["args"])
        self.assertIn("--read-only", cfg["args"])
        self.assertTrue(any(str(self.directory.resolve()) in a for a in cfg["args"]))
        self.assertFalse(any("ARK" in name for name in cfg["env"]))

    def test_cold_scenarios_share_public_state_and_hide_history(self):
        prompts, tables = {}, {}
        def fake(run, turn, gateway, session, prompt, client, **kwargs):
            self.assertEqual(turn, 7)
            self.assertTrue(kwargs["first_session"])
            self.assertEqual(kwargs["allowed"], ALLOWED)
            self.assertFalse(list((client / "desk").iterdir()))
            (run / "trace" / f"turn-{turn}.jsonl").write_text(json.dumps(
                {"type":"system","subtype":"init","tools":sorted(ALLOWED),
                 "mcp_servers":[{"name":"table","status":"connected"}]}) + "\n")
            label = run.name
            prompts[label] = prompt
            tables[label] = game_call(run / "arena", turn, "observe", {}, "client", 1)
            return 1
        with patch("s1.pilot.run_claude", side_effect=fake), patch("s1.pilot.subprocess.check_output",return_value="test"):
            for variant in "AB":
                for arm in ("current", "reminder"):
                    run = self.root / (variant + arm)
                    play(run, variant, 42, "fake-credential", arm, 3)
                    self.assertTrue((run / "snapshots/7.json").is_file())
                    self.assertFalse((run / "snapshots/1.json").exists())
                    self.assertEqual(json.loads((run / "manifest.json").read_text())["status"], "complete")
        for public in tables.values():
            self.assertEqual(public, tables["Acurrent"])
        self.assertEqual(prompts["Acurrent"], prompts["Bcurrent"])
        for variant in "AB":
            self.assertNotIn(scout_notice(variant), prompts["Acurrent"])
            self.assertIn(scout_notice(variant), prompts[variant+"reminder"])

    def test_claude_registration_disconnect_and_unexpected_tool(self):
        path = self.root / "turn.jsonl"
        for status, tools in (("failed", []), ("connected", [*ALLOWED,"Bash"])):
            path.write_text(json.dumps({"type":"system","subtype":"init","tools":tools,
                                       "mcp_servers":[{"name":"table","status":status}]}) + "\n")
            with self.assertRaisesRegex(RuntimeError, "did not connect"):
                verify_client(path)

    def test_smoke_labeled_receipt_exact_read_order_and_write_success(self):
        token = "deadbeef1234"
        label = "交接代号：" + token
        trace = self.run / "trace"
        (trace / "turn-1.jsonl").write_text(json.dumps({"type":"result","result":"读回 " + token}))
        def call(op, arg, reply):
            return {"tool":"act","args":{"action":{"op":op, **arg}}, "result":reply}
        good = call("note", {"text":label}, {"ok":True})
        read = call("read_note", {}, {"ok":True,"note":label})
        for valid, actions in [
            (True, [good, read]),
            (False, [read, good]),
            (False, [good, call("read_note", {}, {"ok":True, "note":token})]),
            (False, [call("note", {"text":label}, {"ok":False}), read]),
            (False, [call("note", {"text":label+"7"}, {"ok":True}),
                     call("read_note", {}, {"ok":True,"note":label+"7"})]),
        ]:
            rows = [{"tool":"observe","args":{},"result":{"venue":"开幕"}}] + actions
            (trace / "tools-1.jsonl").write_text("".join(
                json.dumps(dict(n=n, **row))+"\n" for n, row in enumerate(rows)))
            if valid:
                verify_smoke(self.run, token)
            else:
                with self.assertRaises(RuntimeError):
                    verify_smoke(self.run, token)
