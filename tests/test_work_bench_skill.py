"""Offline regression for the authoring helpers using a published C2 receipt."""

import csv
import json
from pathlib import Path
import runpy
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agent/skills/work-bench/scripts"
score = runpy.run_path(str(SCRIPTS / "score.py"))["score"]
analyze = runpy.run_path(str(SCRIPTS / "calibrate.py"))["analyze"]


class WorkBenchSkillTest(unittest.TestCase):
    def test_frozen_c2_withdrawal_and_excess_notification(self):
        path = ROOT / "rollout/c2/deepseek-v4.1-flash/official/artifacts.tar.gz"
        with tarfile.open(path) as archive:
            batches = json.load(archive.extractfile("receipts/6.json"))
        uid = "M42-20260320"
        final, counts = {}, {}
        for channel, history in batches.items():
            for batch in history:
                if uid in batch["rows"]:
                    final[channel] = batch["rows"][uid]["utc"]
                if batch["turn"] == 6:
                    for sent in batch["rows"]:
                        key = f"{channel}/{sent}"
                        counts[key] = counts.get(key, 0) + 1
        contract = {
            "version": "example",
            "groups": {
                "state": {
                    "weight": 60,
                    "expected": {
                        "A": "2026-03-20T17:00:00Z",
                        "B": "2026-03-20T15:00:00Z",
                    },
                },
                "notices": {"weight": 40, "expected": {f"B/{uid}": 1}},
            },
        }
        observed = {"version": "example", "groups": {"state": final, "notices": counts}}
        self.assertEqual(score(contract, observed)["score"], 100)
        counts[f"A/{uid}"] = 1
        self.assertEqual(score(contract, observed)["score"], 80)
        del observed["groups"]["state"]
        with self.assertRaises(ValueError):
            score(contract, observed)

    def test_protocol_and_noncompletion_remain_separate(self):
        rows = csv.DictReader(
            """task,instance,condition,model,run,status,score
C2,17217/A,v1,A,1,complete,68
C2,17217/A,v1,A,2,complete,72
C2,17217/A,v1,B,1,complete,59
C2,17217/A,v1,B,2,complete,61
C2,17217/A,v1,B,3,budget_stop,
C2,17217/A,v2,A,1,complete,100""".splitlines()
        )
        first, second = analyze(rows, 95)
        self.assertEqual(first["models"]["A"]["variance"], 8)
        self.assertEqual(first["models"]["B"]["n"], 2)
        self.assertEqual(first["models"]["B"]["attempts"], 3)
        self.assertEqual(first["contrasts"][0]["observed_gap_min"], 7)
        self.assertEqual(first["contrasts"][0]["mean_a_minus_b"], 10)
        self.assertIsNone(second["models"]["A"]["sd"])
        self.assertEqual(second["contrasts"], [])
