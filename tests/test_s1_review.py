import json
from pathlib import Path
import tempfile
import unittest

from s1.review import audit


class TraceAuditTest(unittest.TestCase):
    def test_corrupt_traces_and_missing_receipts_are_diagnosed(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            trace = run / "trace"
            trace.mkdir()
            (run / "manifest.json").write_text(json.dumps({"session": "s", "status": "complete",
                "turns": [{"turn": 1, "upstream_calls": 2}]}), encoding="utf-8-sig")
            (trace / "api-0001.json").write_text('{"turn":')
            (trace / "turn-1.jsonl").write_text('{}\n{"type":"assistant","message":null}\n')
            (trace / "tools-1.jsonl").write_text('{"result":null}')
            flags = audit(run)["audit_flags"]
            self.assertTrue(any("api-0001.json" in f for f in flags))
            self.assertTrue(any("turn-1.jsonl" in f for f in flags))
            self.assertTrue(any("tools-1.jsonl" in f for f in flags))
            self.assertTrue(any("attempt count" in f for f in flags))

    def test_matches_complete_exchange_and_detects_changed_return(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            trace = run / "trace"
            trace.mkdir()
            (run / "manifest.json").write_text(json.dumps({"session": "session", "status": "complete"}))
            name, cid = "mcp__table__observe", "call-1"
            provider = {"turn": 1, "status": 200,
                        "request": {"tools": [{"function": {"name": name}}]},
                        "response": {"id": "receipt", "model": "test",
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                            "choices": [{"message": {"tool_calls": [{"id": cid, "function": {
                                "name": name, "arguments": "{}"}}]}}]}}
            (trace / "api-0001.json").write_text(json.dumps(provider))
            payload = {"table": "open"}
            messages = [
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": cid,
                                                               "name": name, "input": {}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": cid,
                                    "content": [{"type": "text", "text": json.dumps(payload)}]}]}},
                {"type": "result", "is_error": False}]
            (trace / "turn-1.jsonl").write_text("\n".join(json.dumps(dict(m, session_id="session")) for m in messages))
            host = trace / "tools-1.jsonl"
            row = {"tool": "observe", "args": {}, "result": payload}
            host.write_text(json.dumps(row))
            self.assertEqual(audit(run)["audit_flags"], [])
            host.write_text(json.dumps(dict(row, result={"other": True})))
            self.assertIn("actual tool exchanges differ", audit(run)["audit_flags"][0])
