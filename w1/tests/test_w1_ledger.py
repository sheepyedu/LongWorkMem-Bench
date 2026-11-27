import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from w1.grade import grade
from w1.reference import solve_turn
from w1.runstate import freeze, prepare
from w1.scoring_oracle import PAY, expected
from w1.scoring_tables import Table
from w1.world import release


class LedgerScoringTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name) / "run"

    def test_first_delivery_uses_only_original_material_and_retains_later_credit(self):
        work = prepare(self.run)
        for turn in (1, 2):
            release(work, turn, "A")
            solve_turn(work, turn)
            freeze(self.run, turn)
        result = grade(self.run, "A")
        self.assertEqual(result["items"]["CP1.initial"]["earned"], 4)

        first, second = (self.run / "snapshots" / str(turn) for turn in (1, 2))
        shutil.copyfile(second / "current.csv", first / "current.csv")
        self.assertEqual(grade(self.run, "A")["items"]["CP1.initial"]["earned"], 2)
        shutil.rmtree(first)
        missing = grade(self.run, "A")["items"]
        self.assertEqual(missing["CP1.initial"]["earned"], 0)
        self.assertEqual(sum(i["earned"] for key, i in missing.items() if key.startswith("CP1.")), 11)

    def test_payroll_parse_error_is_local_to_the_employee_group(self):
        pay = expected("A")["pay"]
        self.run.mkdir()
        path = self.run / "pay.csv"
        for employee, expected_credit in [("E01", (True, False)), ("E07", (False, True))]:
            with self.subTest(employee=employee):
                with path.open("w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=PAY.split())
                    writer.writeheader()
                    for row in pay:
                        hours = "待复核" if row["employee"] == employee else row["hours"]
                        writer.writerow(dict(row, hours=hours, employee=f" {row['employee']} "))
                table = Table(path)
                scoped = table.matches(pay, PAY, predicate=lambda r: r["employee"] == "E07")
                others = table.matches(pay, PAY, predicate=lambda r: r["employee"] != "E07")
                self.assertEqual((scoped[0], others[0]), expected_credit)
                self.assertFalse(table.matches(pay, PAY)[0])
