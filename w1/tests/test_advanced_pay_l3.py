from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_pay, advanced_pay_l3 as l3
from w1.reference import read_csv
from w1.runstate import freeze, prepare


class ThirdLevelPayTests(unittest.TestCase):
    def test_public_releases_withdraw_source_and_restore_pay_from_archive(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp) / "office"
            work = prepare(run)
            for turn in range(1, 10):
                l3.release(work,turn,"B",3,431)
                if turn == 2:
                    self.assertTrue((work / l3.REGISTER).is_file())
                if turn >= 4:
                    self.assertFalse((work / l3.REGISTER).exists())
                    self.assertFalse((work / l3.CONTRACTS).exists())
                l3.reference(run,turn,"B",3,431)
                freeze(run,turn)
            raw = read_csv(work / "input/工时中心/主账.csv")
            self.assertIn("badge",raw[0])
            self.assertNotIn("employee",raw[0])
            roster = l3.expected_pay("B",3,431)
            self.assertEqual(roster, advanced_pay.expected_pay("B",2,431))
            checks = l3.checks(run,"B",3,431)
            self.assertEqual(sum(v[1] for v in checks.values()),35)
            self.assertEqual(sum(v[0] for v in checks.values()),35,checks)
            (run / "snapshots/3/frozen/payroll-index.csv").unlink()
            changed = l3.checks(run,"B",3,431)
            self.assertEqual(sum(v[0] for v in changed.values()),27,changed)
            (work / "out/frozen/payroll-index.csv").unlink()
            with self.assertRaises((OSError,ValueError)):
                l3.reference(run,7,"B",3,431)

    def test_reused_badge_and_signed_version(self):
        with TemporaryDirectory() as tmp:
            work=prepare(Path(tmp) / "office")
            for turn in (1,2):
                l3.release(work,turn,"A",3,913)
            rows = l3.compile_index(work)
            self.assertEqual(len(rows),96)
            one = [r for r in rows if r["site"]=="西厂" and r["badge"]==rows[0]["badge"]]
            self.assertEqual(len(one),2)
            self.assertNotEqual(one[0]["employee"],one[1]["employee"])
            self.assertGreater(len({r["rate"] for r in rows}),1)
            self.assertTrue(all(Decimal(str(r["rate"]))>0 for r in rows))
