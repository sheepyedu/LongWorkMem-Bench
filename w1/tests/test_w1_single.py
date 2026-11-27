import csv
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from w1 import advanced, pilot
from w1.scorecard import OUTCOMES, PROCESS
from w1.scoring_tables import Table


class SingleSessionTests(unittest.TestCase):
    def test_cli_starts_one_session_directly_in_destination(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "new-run"
            with patch("sys.argv", ["pilot", str(dest)]), patch.object(pilot, "provider", return_value=("url", "key")), \
                    patch.object(pilot, "play") as play:
                pilot.main()
            play.assert_called_once_with(dest.resolve(), "A", "docker", "key", False, None,
                                         model=pilot.MODEL, url="url", level=8, seed=17217, erp_window=False)
            self.assertFalse(dest.exists())

    def test_outcome_and_turn_evidence_are_scored_once(self):
        probes = [row[-1].split() for row in (*PROCESS, *OUTCOMES)]
        keys = [key for checkpoint in probes for key in checkpoint]
        self.assertEqual(len(keys), len(set(keys)))
        with TemporaryDirectory() as tmp:
            run = Path(tmp) / "single"
            advanced.run_reference(run, "A", 8, 1733)
            baseline = advanced.grade(run)
            self.assertEqual(baseline["total"], 100)
            items = baseline["items"]
            self.assertEqual(len(items), 13)
            self.assertEqual(sum(x["max"] for x in items.values() if x["department"] == "process"), 30)
            self.assertEqual(sum(x["max"] for x in items.values() if x["department"] == "outcome"), 70)
            for name in ("meeting.csv", "priority.csv"):
                (run / "snapshots/4" / name).unlink()
            filing = run / "snapshots/9/reserve/2025-08-05.csv"
            table = Table(filing)
            table.rows[0]["desk"] = "错岗"
            table.rows[0]["authority"] = "错误批文"
            with filing.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=table.headers)
                writer.writeheader()
                writer.writerows(table.rows)
            revised = advanced.grade(run, details=True)["items"]
            changed = {k for k in items if items[k]["earned"] != revised[k]["earned"]}
            self.assertEqual(changed, {"round.4", "result.reserve"})
            self.assertEqual(revised["round.4"]["earned"], 0)
            self.assertAlmostEqual(revised["result.reserve"]["earned"], 20 - 4 / 36, places=5)
            self.assertIn("35/36", revised["result.reserve"]["evidence"]["memory.r9.case"]["reason"])
            for directory in (run / "snapshots").iterdir():
                shutil.rmtree(directory)
                directory.mkdir()
            shutil.rmtree(run / "mail")
            (run / "mail").mkdir()
            empty = advanced.grade(run)
            self.assertEqual(empty["total"], 0, empty["items"])
