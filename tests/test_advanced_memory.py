from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_memory as mem


class MandateTests(unittest.TestCase):
    def test_partial_withdrawal_expiry_and_transfer(self):
        rules = mem.mandate(431)
        row = dict(office="南港", case="X", kind=rules["kind"], employee="E07", project="共享",
                   worked="2025-07-16", vendor="常规", amount="1.00")
        active = mem.decision(row, "2025-08-04", rules, "2025-07-16")
        historical = mem.decision(row, "2025-08-04", rules, "2025-08-16")
        self.assertEqual((active["project"], active["authority"]), ("乙", rules["temporary"]))
        self.assertEqual(historical["project"], "甲")
        restored = mem.decision(row, "2025-08-05", rules, "2025-07-16")
        self.assertEqual(restored["authority"], rules["base_id"])
        withdrawn = mem.decision(dict(row,office="江东"), "2025-08-04", rules, "2025-07-16")
        self.assertEqual(withdrawn["authority"], rules["base_id"])
        stop = mem.decision(dict(row,vendor=rules["vendor"]), "2025-08-04", rules, "2025-07-16")
        self.assertEqual((stop["decision"], stop["target"]), ("HOLD", 0))

    def test_delta_uses_filed_amount_and_duplicate_has_no_unique_receipt(self):
        from w1.world import _csv
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/"posted.csv"
            _csv(p,"office,case,target",[("南港","K03","37.000"),("江东","K03",10),("江东","K03",20)])
            self.assertEqual(mem.filed_amounts(p), {("南港","K03"):37})

    def test_control_preserves_same_office_and_exposes_only_prior_postings(self):
        from w1.controls import seed_digest
        from w1.memory_control import fixture
        with TemporaryDirectory() as tmp:
            offices = [Path(tmp) / n / "work" for n in ("left","right")]
            instructions = [fixture(p, 431, "A", 8) for p in offices]
            self.assertEqual(seed_digest(offices[0]), seed_digest(offices[1]))
            self.assertEqual(instructions[0], instructions[1])
            self.assertEqual(len(instructions[0]), 3)
            self.assertTrue((offices[0]/"out"/mem.form(5)).is_file())
            self.assertFalse((offices[0]/"out"/mem.form(8)).exists())
            self.assertFalse((offices[0]/"input/资金运营/争议清册/2025-08-05.csv").exists())

    def test_copied_answer_cannot_pass_date_sensitive_pair(self):
        from w1.world import _csv
        with TemporaryDirectory() as tmp:
            runs = {v:Path(tmp)/v for v in "AB"}
            for turn in (8,9):
                rows = mem.posting(mem.cases(turn,431),turn,mem.mandate(431),"2025-07-16",{})
                for run in runs.values():
                    _csv(run/"snapshots"/str(turn)/mem.form(turn),mem.FIELDS,
                         [[r[k] for k in mem.FIELDS.split(",")] for r in rows])
            result = mem.contrast(runs,431)
            self.assertGreater(result["must_change"]["cases"],0)
            self.assertEqual(result["must_change"]["matched_both"],0)
            self.assertEqual(result["must_stay"]["matched_both"],result["must_stay"]["cases"])

    def test_one_bad_desk_and_filed_amount_still_allow_correct_next_adjustment(self):
        from w1 import advanced
        from w1.runstate import ROUNDS, prepare, freeze
        from w1.scoring_tables import Table
        from w1.world import _csv
        with TemporaryDirectory() as tmp:
            run = Path(tmp)/"run"
            work = prepare(run)
            for turn in ROUNDS:
                advanced.release(work,turn,"A",7,431)
                mem.reference(run,turn,"A",7,431)
                if turn == 8:
                    path = work/"out"/mem.form(turn)
                    rows = Table(path).rows
                    rows[0]["desk"] = "错岗"
                    rows[0]["target"] = str(int(rows[0]["target"])+10)
                    _csv(path, mem.FIELDS, [[r[k] for k in mem.FIELDS.split(",")] for r in rows])
                freeze(run,turn)
            score = mem.checks(run,"A",7,431)
            self.assertAlmostEqual(score["memory.r8.desk"][0],35/36)
            self.assertAlmostEqual(score["memory.r8.amount"][0],35/36)
            self.assertEqual(score["memory.r8.authority"][0],1)
            self.assertEqual(score["memory.r9.adjustment"][0],3)
            self.assertEqual(score["memory.retention"][0],2)
