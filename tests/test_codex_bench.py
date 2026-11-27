"""Codex-specific replay invariants, independent of network and login."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tasks.codex_bench import native_usage, recorded_turn, verify_threads


class CodexReplayTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name)
        self.trace = self.run / "trace"
        self.trace.mkdir()
        self.rows = []
        self.log(
            "send",
            id=1,
            method="turn/start",
            params=dict(
                threadId="first", input=[dict(type="text", text="R1")], environments=[]
            ),
        )
        self.log("recv", id=1, result=dict(turn=dict(id="turn")))
        self.event(
            "item/tool/call",
            dict(tool="office_shell", arguments={}, callId="call"),
            id=8,
        )
        output = dict(success=True, contentItems=[dict(type="inputText", text="123")])
        self.log("send", id=8, result=output)
        self.event(
            "item/completed",
            dict(
                item=dict(
                    type="dynamicToolCall",
                    id="call",
                    tool="office_shell",
                    arguments={},
                    **output,
                )
            ),
        )
        self.event("item/completed", dict(item=dict(type="agentMessage", text="done")))
        self.event("turn/completed", dict(turn=dict(id="turn", status="completed")))

    def log(self, direction, **message):
        self.rows.append(dict(direction=direction, message=message))

    def event(self, method, params, **kw):
        self.log(
            "recv",
            method=method,
            params=dict(threadId="first", turnId="turn", **params),
            **kw,
        )

    def replay(self, thread="first"):
        (self.trace / "turn-1.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in self.rows)
        )
        return recorded_turn(self.run, 1, thread, "R1", ["office_shell"])

    def test_round_trip_and_fresh_thread(self):
        self.assertEqual(self.replay(), "done")
        with self.assertRaises(ValueError):
            self.replay("old-thread")

    def test_altered_tool_output_rejected(self):
        self.rows[3]["message"]["result"]["contentItems"] = []
        with self.assertRaises(ValueError):
            self.replay()

    def test_missing_completion_rejected(self):
        self.rows.pop()
        with self.assertRaises(ValueError):
            self.replay()

    def test_reused_handover_session_rejected(self):
        row = dict(model="x", effort="low", tools=[], thread="same")
        (self.trace / "threads.jsonl").write_text((json.dumps(row) + "\n") * 2)
        with self.assertRaises(ValueError):
            verify_threads(self.run, dict(model="x", effort="low"), "s1", [1, 41])

    def test_usage_is_cumulative_per_session(self):
        for idx, (thread, n) in enumerate([("a", 21), ("a", 45), ("b", 19)], 1):
            total = dict(
                inputTokens=n,
                cachedInputTokens=0,
                totalTokens=n + 1,
                outputTokens=1,
                reasoningOutputTokens=0,
            )
            row = dict(
                message=dict(
                    method="thread/tokenUsage/updated",
                    params=dict(threadId=thread, tokenUsage=dict(total=total)),
                )
            )
            (self.trace / f"turn-{idx}.jsonl").write_text(json.dumps(row) + "\n")
        meta = dict(turns=[dict(attempts=[i]) for i in (1, 2, 3)])
        self.assertEqual(native_usage(self.run, meta)["inputTokens"], 64)
        (self.trace / "turn-3.jsonl").write_text("")
        result = native_usage(self.run, meta)
        self.assertEqual(result["missing_usage_attempts"], [3])
        self.assertNotIn("inputTokens", result)
