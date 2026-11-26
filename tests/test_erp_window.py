from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from w1.erp_window import LIMITS, windowed_shell


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
        with patch("w1.office.shell", return_value={"status":1, "output":"bad file"}) as shell:
            first = self.call(5)
            self.assertEqual(first, self.call(5))
            self.assertEqual(shell.call_count, 1)
            self.assertEqual(first["remaining_batches"], LIMITS[4]-1)
            # A restarted MCP client can start numbering requests at the same value.
            self.assertEqual(self.call(5,"different")["remaining_batches"], LIMITS[4]-2)
            self.assertEqual(self.call(5,turn=5)["remaining_batches"], LIMITS[5]-1)

    def test_concurrent_requests_stop_at_the_announced_limit(self):
        with patch("w1.office.shell", return_value={"status":0, "output":"ok"}) as shell, ThreadPoolExecutor(8) as pool:
            results = list(pool.map(self.call, range(10)))
        self.assertEqual(shell.call_count, LIMITS[4])
        self.assertEqual(sum(r.get("window_closed", False) for r in results), 10-LIMITS[4])
        self.assertTrue(all(r["remaining_batches"] >= 0 for r in results))
