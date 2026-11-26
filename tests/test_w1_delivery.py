from pathlib import Path
import shutil
import tempfile
import unittest

from openpyxl import load_workbook

from w1.grade import grade
from w1.mail import act
from w1.reference import run_reference
from w1.scoring_mail import check_mail
from w1.scoring_oracle import expected
from w1.scoring_tables import Table
from w1.scoring_workbook import check_workbook


class CheckpointDeliveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.reference = Path(directory.name) / "reference"
        run_reference(cls.reference, "A")
        cls.oracle = expected("A")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.run = Path(directory.name) / "run"
        shutil.copytree(self.reference, self.run)
        self.final = self.run / "snapshots/9"

    def test_late_workbook_repair_does_not_make_round_seven_formulas_live(self):
        path = self.run / "snapshots/7/bonus.xlsx"
        book = load_workbook(path)
        awards = {(r["project"], r["employee"]): r["bonus"] for r in self.oracle["pay"]}
        for project, employee, hours, bonus, *_ in list(book["Pay"].rows)[1:]:
            bonus.value = float(awards[project.value, employee.value])
        book.save(path)
        result = grade(self.run, "A")
        self.assertEqual(result["infrastructure_anomalies"], [])
        self.assertEqual(result["items"]["CP5.recalc"]["earned"], 2)

    def test_each_employee_hours_cell_controls_their_award(self):
        path = self.final / "bonus.xlsx"
        book = load_workbook(path)
        pay = book["Pay"]
        row = next(c.row for c in pay["B"] if c.value == "E01")
        # A stale hours subtotal keeps one person's original hours when their input changes.
        initial_hours = pay[f"C{row}"].value
        for total in list(pay["F"])[1:]:
            total.value += f"-$C${row}+{initial_hours}"
        book.save(path)
        checks, anomalies = check_workbook(path, self.oracle, Table(self.final / "pay.csv"))
        self.assertEqual(anomalies, [])
        self.assertEqual([ok for ok, _ in checks], [True, False, True])
        self.assertIn("E01", checks[1][1])

    def test_payroll_workbook_action_before_approval_counts_as_payroll(self):
        for action in ("draft", "deliver"):
            with self.subTest(action=action):
                receipt = act(self.run, 7, action, "finance@office.test", "out/bonus.xlsx", "七月奖金工作簿")
                evidence, archive, anomalies, incidental, incidents, approved = check_mail(
                    self.run, self.final, self.oracle)
                self.assertEqual(anomalies, [])
                self.assertFalse(approved)
                self.assertNotIn(receipt, [e["receipt"] for e in incidental])
                self.assertEqual([e["receipt"] for e in incidents], [receipt] if action == "deliver" else [])
                self.assertEqual(sum(w for w, (ok, _) in evidence if ok), 5)
                self.assertEqual(sum(w for w, (ok, _) in archive if ok), 3)
                shutil.rmtree(self.run / "mail/7" / receipt)

    def test_round_seven_csv_typo_preserves_independently_working_formulas(self):
        early = self.run / "snapshots/7/pay.csv"
        self.assertEqual((self.run / "snapshots/7/bonus.xlsx").read_bytes(),
                         (self.final / "bonus.xlsx").read_bytes())
        self.assertIn("689.65", early.read_text())
        early.write_text(early.read_text().replace("689.65", "689.66"))
        result = grade(self.run, "A")
        self.assertEqual(result["infrastructure_anomalies"], [])
        self.assertEqual(result["items"]["CP5.recalc"]["earned"], 8)
        self.assertIn("R7", result["items"]["CP5.recalc"]["reason"])

    def test_self_consistent_workbook_and_csv_with_wrong_roster_fail_recalculation(self):
        path = self.final / "bonus.xlsx"
        payroll = self.final / "pay.csv"
        book = load_workbook(path)
        employee = next(cell for cell in book["Pay"]["B"] if cell.value == "E03")
        employee.value = "E33"
        book.save(path)
        payroll.write_text(payroll.read_text().replace("E03", "E33"))
        checks, anomalies = check_workbook(path, self.oracle, Table(payroll))
        self.assertEqual(anomalies, [])
        self.assertFalse(any(ok for ok, _ in checks))
