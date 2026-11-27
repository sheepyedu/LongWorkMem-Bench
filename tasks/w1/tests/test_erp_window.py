from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tasks.w1.erp_window import LIMITS, windowed_shell
from tasks.w1.paired import window_receipts


class WindowTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name)
        (self.run / "trace").mkdir()
        (self.run / "work").mkdir()

    def call(self, i, command="read", turn=4):
        return windowed_shell(self.run, turn, i, command)

    def test_retry_spends_one_slot_and_original_bad_command_counts(self):
        with patch("tasks.w1.office.shell", return_value={"status":1, "output":"bad file"}) as shell:
            first = self.call(5)
            self.assertEqual(first, self.call(5))
            self.assertEqual(shell.call_count, 1)
            self.assertEqual(first["remaining_batches"], LIMITS[4]-1)
            # A restarted MCP client can start numbering requests at the same value.
            self.assertEqual(self.call(5,"different")["remaining_batches"], LIMITS[4]-2)
            self.assertEqual(self.call(5,turn=5)["remaining_batches"], LIMITS[5]-1)

    def test_concurrent_requests_stop_at_the_announced_limit(self):
        with patch("tasks.w1.office.shell", return_value={"status":0, "output":"ok"}) as shell, ThreadPoolExecutor(8) as pool:
            results = list(pool.map(self.call, range(10)))
        self.assertEqual(shell.call_count, LIMITS[4])
        self.assertEqual(sum(r.get("window_closed", False) for r in results), 10-LIMITS[4])
        self.assertTrue(all(r["remaining_batches"] >= 0 for r in results))

    def test_paired_audit_checks_provider_window_receipts(self):
        import json
        from tasks.w1.runstate import ROUNDS
        for turn in ROUNDS:
            (self.run / f"trace/turn-{turn}.jsonl").write_text("")
        with patch("tasks.w1.office.shell", return_value={"status":0, "output":"ok"}):
            for i in range(LIMITS[4]+1):
                event = self.call(i)
                with (self.run / "trace/turn-4.jsonl").open("a") as f:
                    call = {"type":"assistant","message":{"content":[{"type":"tool_use",
                        "name":"mcp__office__shell","id":str(i)}]}}
                    feedback = {"type":"user","message":{"content":[{"type":"tool_result",
                        "tool_use_id":str(i), "content":[{"type":"text","text":json.dumps(event)}]}]}}
                    for row in (call, feedback):
                        f.write(json.dumps(row)+"\n")
        self.assertEqual(window_receipts(self.run)[4], {"allowed":5,"used":5,"closed_replies":1})
        (self.run / "trace/erp-window.sqlite").unlink()
        with self.assertRaisesRegex(ValueError, "window"):
            window_receipts(self.run)

    def test_short_shift_uses_its_announced_allowance(self):
        from tasks.w1.erp_window import limits_for, notice
        limits = limits_for(6)
        self.assertEqual(list(limits.values()), [4, 5, 3, 3, 5, 3, 6, 5, 5])
        self.assertIn("4批", notice(1, 6))
        with patch("tasks.w1.office.shell", return_value={"status":0, "output":"ok"}):
            for i in range(4):
                result = windowed_shell(self.run, 1, i, "read", limits=limits)
                self.assertEqual(result["remaining_batches"], 3-i)
            self.assertTrue(windowed_shell(self.run, 1, 5, "read", limits=limits)["window_closed"])
