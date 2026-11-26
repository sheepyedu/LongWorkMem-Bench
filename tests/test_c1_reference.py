"""End-to-end reference tracks run the public CLI inside the selected C1 sandbox."""
import csv
import json
import os
import platform
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from c1 import sandbox
from c1.reference import run_reference


BACKEND = "docker" if os.getenv("C1_TEST_DOCKER") == "1" else "seatbelt"


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@unittest.skipUnless(platform.system() == "Darwin" or BACKEND == "docker",
                     "requires macOS Seatbelt or C1_TEST_DOCKER=1")
class ReferenceWalkthroughTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory(dir=os.getenv("C1_TEST_ROOT"))
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.runs = {name: run_reference(cls.root / name, name[0],
                                        alternate=name.endswith("-alternate"), backend=BACKEND)
                    for name in ("A", "B", "B-alternate")}

    def test_all_three_tracks_pass_independent_grade(self):
        from c1.grade import grade
        for name, run in self.runs.items():
            with self.subTest(name=name):
                result = grade(run, name[0], backend=BACKEND)
                self.assertEqual(result["infrastructure_errors"], [])
                self.assertEqual(result["total"], 100, result["checks"])
                self.assertEqual(result["dependency"]["earned"], 14)

    def test_interruption_and_return_are_frozen_at_the_business_boundary(self):
        run = self.runs["A"]
        result = json.loads((run / "fault.json").read_text())
        self.assertEqual(result["status"], 86)
        witness = json.loads(result["output"])
        self.assertEqual(witness["visible"], ["s17-01", "s17-02"])
        self.assertTrue(witness["in_transaction"])
        for turn, count in (("fault", 16), ("snapshots/7", 16), ("snapshots/8", 20)):
            with self.subTest(turn=turn), tempfile.TemporaryDirectory() as temp:
                from c1.runstate import freeze
                copy = Path(temp) / "work"
                freeze(run / turn, copy)
                with closing(sqlite3.connect(copy / "data/tickets.sqlite")) as conn:
                    actual = conn.execute("SELECT shard FROM commits ORDER BY shard").fetchall()
                    self.assertEqual(actual, [(f"{i:03}.jsonl",) for i in range(1, count+1)])
                    arrived = conn.execute("SELECT COUNT(*) FROM events WHERE event_id LIKE 's17-%'").fetchone()
                    self.assertEqual(arrived[0], 4 if count == 20 else 0)
        self.assertEqual((run / "snapshots/7/out/failed.txt").read_bytes(),
                         (run / "snapshots/8/out/failed.txt").read_bytes())

    def test_withdrawal_retains_scoped_correction_in_history_only(self):
        readings = []
        for name in ("A", "B"):
            latest = self.runs[name] / "snapshots/11"
            history = {(r["source"], r["ticket"]): r for r in csv_rows(latest / "out/history.csv")}
            self.assertIn(("B", "0017"), history)
            historic = history.pop(("A", "0017"))
            self.assertEqual((historic["revision"], historic["status"]), ("3", "closed"))
            command = "python3 project/tickets.py query data/tickets.sqlite"
            live = sandbox.shell(self.runs[name] / "work", command, backend=BACKEND)
            self.assertEqual(live["status"], 0, live)
            current = json.loads(live["output"])
            self.assertNotIn(("A", "0017"), [(r["source"], r["ticket"]) for r in current])
            readings.append((historic["dept"], history, current, csv_rows(latest / "out/current.csv")))
        self.assertNotEqual(readings[0][0], readings[1][0])
        self.assertEqual(readings[0][1:], readings[1][1:])

    def test_alternate_json_representation_and_read_model_are_equivalent(self):
        results = []
        for name in ("B", "B-alternate"):
            path = self.runs[name] / "trace/09.json"
            trace = json.loads(path.read_text())
            results.append(trace["commands"][-1]["output"])
        self.assertNotEqual(*results)
        self.assertEqual(*map(json.loads, results))
        self.assertNotEqual(*[(self.runs[name] / "snapshots/12/project/views.py").read_bytes()
                              for name in ("B", "B-alternate")])
