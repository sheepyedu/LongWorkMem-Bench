import json
import os
import tempfile
import unittest
from pathlib import Path

from tasks.w4.quota import settlement
from tasks.w4.quota.promise_score import integer_matches, scorecard
from tasks.w4.quota.score import score
from tasks.w4.tests.quota_controls import play


class PromiseTests(unittest.TestCase):
    def test_equivalent_seat_counts(self):
        for v in ("02", "２.００", 2.0):
            self.assertTrue(integer_matches(2, v))
        for v in ("2.1", "2席", True, None):
            self.assertFalse(integer_matches(2, v))

    def test_early_agreement_and_later_stop_have_bounded_effect(self):
        history = {"J07": {"实占": 4}}
        # The same certificate amount (3) and legacy entitlement (2) occur
        # at the same cutoff. Only the archived legal relationship differs.
        self.assertEqual(settlement.entitlement("J01", 9, 9, history, 2), 3)
        self.assertEqual(settlement.entitlement("J04", 9, 9, history, 2), 5)
        self.assertEqual(settlement.entitlement("J01", 11, 9, history, 2), 3)
        self.assertEqual(settlement.entitlement("J01", 11, 11, history, 2), 2)
        self.assertEqual(settlement.entitlement("J04", 11, 11, history, 2), 5)

    @unittest.skipUnless(os.getenv("W4_TEST_ROOT"), "requires W4 Docker Calc")
    def test_gold_and_execution_ordering(self):
        root = Path(__file__).resolve().parents[3]
        old_model = json.loads(
            (root / "rollout/w4/deepseek-v4.1-flash/v4/grade.json").read_text()
        )
        new_model, counts = scorecard(old_model["atoms"])
        self.assertEqual(counts["customer_days_correct"], 42)
        with tempfile.TemporaryDirectory() as td:
            for name, advanced in [
                ("gold", True),
                ("ignore_feedback", False),
                ("empty", True),
            ]:
                path = Path(td) / name
                play(path, name, promise=advanced)
                g = score(path)
                if name == "gold":
                    self.assertEqual(g["total"], 100)
                    self.assertEqual(g["fulfilment"]["customers_always_correct"], 12)
                elif name == "empty":
                    self.assertEqual(g["total"], 0)
                else:
                    self.assertGreater(g["total"], old_model["total"])
                    new_weak, counts = scorecard(g["atoms"])
                    self.assertEqual(counts["customer_days_correct"], 29)
                    self.assertLess(
                        sum(x["earned"] for x in new_weak),
                        sum(x["earned"] for x in new_model),
                    )

    @unittest.skipUnless(os.getenv("W4_TEST_ROOT"), "requires W4 Docker Calc")
    def test_partial_capacity_probes_and_retired_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "desk"
            play(root, "all_or_wait", promise=True)
            g = score(root)
            self.assertEqual(g["fulfilment"]["customer_days_correct"], 48)
            fields = {a["field"] for a in g["atoms"] if a["earned"] == 0}
            self.assertIn("预约-部分容量兑现", fields)
            self.assertNotIn("预约-增容响应", fields)
            self.assertNotIn("预约-停办响应", fields)
            self.assertFalse((root / "work/inbox/06-02/历史保障签章表.csv").exists())
            self.assertTrue((root / "work/inbox/06-07/划转单.csv").is_file())
