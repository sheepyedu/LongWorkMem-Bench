import json
from pathlib import Path
import tempfile
import unittest

from w1.review import summarize


class ReviewTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.run = Path(temp.name)
        self.trace = self.run / "trace"
        self.trace.mkdir()

    def manifest(self, turns, status="complete"):
        (self.run / "manifest.json").write_text(json.dumps({
            "status": status,
            "turns": [{"turn": t, "upstream_calls": n} for t, n in turns],
        }))

    def attempt(self, number, turn, receipt=True):
        row = {"n": number, "turn": turn, "request": {}}
        if receipt:
            row["response"] = {"id": str(number), "model": "office-model",
                               "usage": {"prompt_tokens": 12, "completion_tokens": 1}}
        (self.trace / f"api-{number:04}.json").write_text(json.dumps(row))

    def test_missing_record_and_present_attempt_without_receipt_are_distinct(self):
        self.manifest([(1, 2), (2, 2)])
        self.attempt(1, 1)
        self.attempt(3, 2, receipt=False)
        result = summarize(self.run)
        self.assertEqual(result["missing_request_files"], ["api-0002.json", "api-0004.json"])
        self.assertEqual(result["attempts_without_usage"], ["api-0003.json"])
        self.assertEqual(result["turns"][1]["expected_attempts"], 2)
        self.assertEqual(result["turns"][2]["attempts"], 1)
        self.assertEqual(result["observed_usage"]["successful"], 1)

    def test_misattributed_request_and_unfinished_turn(self):
        self.manifest([(7, 1)], status="error")
        self.attempt(1, 6)
        self.attempt(2, 8)
        result = summarize(self.run)
        self.assertEqual(result["missing_request_files"], [])
        self.assertEqual(result["request_record_issues"], [
            {"file": "api-0001.json", "reason": "expected turn 7, recorded turn 6"}])

    def test_invalid_record_and_unexpected_complete_run_tail(self):
        self.manifest([(7, 1)])
        (self.trace / "api-0001.json").write_text("{")
        self.attempt(2, 7)
        result = summarize(self.run)
        self.assertEqual(result["missing_request_files"], [])
        self.assertEqual([row["file"] for row in result["request_record_issues"]],
                         ["api-0001.json", "api-0002.json"])
        self.assertEqual(result["turns"][7]["expected_attempts"], 1)

    def test_shell_status_and_mcp_error_are_separate(self):
        self.manifest([(7, 1)])
        self.attempt(1, 7)
        events = []
        for tag, tool, value, error in [
            ("a", "shell", {"status": 124, "output": "internal command diagnostic"}, False),
            ("b", "shell", {"status": 0, "output": "recovered"}, False),
            ("c", "deliver", "bad recipient", True),
            ("d", "draft", {"receipt": "D-123"}, False),
        ]:
            call = {"type": "tool_use", "name": "mcp__office__" + tool, "id": tag}
            result = {"type": "tool_result", "tool_use_id": tag, "is_error": error,
                      "content": [{"type": "text", "text": json.dumps(value)}]}
            events.extend([{"type": "assistant", "message": {"content": [call]}},
                           {"type": "user", "message": {"content": [result]}}])
        (self.trace / "turn-7.jsonl").write_text("\n".join(map(json.dumps, events)))
        result = summarize(self.run)
        self.assertEqual(result["turns"][7]["tool_protocol_errors"], 1)
        self.assertEqual(result["turns"][7]["shell_nonzero_exits"], 1)
        self.assertEqual(result["shell_failures"], [{"file": "turn-7.jsonl", "line": 2, "status": 124}])
        self.assertNotIn("internal command diagnostic", json.dumps(result))

    def test_partial_cli_line_preserves_other_turns_and_prints_location(self):
        self.manifest([(1, 1), (2, 1)])
        self.attempt(1, 1)
        self.attempt(2, 2)
        (self.trace / "turn-1.jsonl").write_bytes(
            b'{"type":"system"}\n{"type": "assista' + b'\xe8')
        (self.trace / "turn-2.jsonl").write_text('{"type":"system","subtype":"compact_boundary"}\n')
        result = summarize(self.run)
        self.assertEqual(result["turn_record_issues"],
                         [{"file": "turn-1.jsonl", "line": 2, "reason": "unreadable Claude event"}])
        self.assertEqual(result["turns"][2]["compactions"], 1)

    def test_duplicate_receipt_and_incomplete_usage_do_not_inflate_observed_totals(self):
        self.manifest([(7, 5)])
        for n in range(1, 6):
            self.attempt(n, 7)
        for n, response in [(2, {"id": "1", "usage": {"prompt_tokens": 12, "completion_tokens": 1}}),
                            (3, None), (4, {"id": "4", "usage": {"prompt_tokens": 14}})]:
            path = self.trace / f"api-{n:04}.json"
            row = json.loads(path.read_text())
            row["response"] = response
            path.write_text(json.dumps(row))
        result = summarize(self.run)
        self.assertEqual(result["attempts_without_usage"], ["api-0003.json", "api-0004.json"])
        self.assertEqual(result["observed_usage"]["successful"], 2)
        self.assertEqual(result["observed_usage"]["input"], 24)
        self.assertEqual(result["request_record_issues"], [
            {"file": "api-0002.json", "reason": "duplicate upstream receipt"},
            {"file": "api-0004.json", "reason": "incomplete or invalid usage"}])
