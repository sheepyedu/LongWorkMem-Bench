import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook

from w1.grade import grade
from w1.reference import run_reference
from w1.scoring_oracle import expected
from w1.scoring_tables import Table
from w1.scoring_workbook import check_workbook


class GradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.base.cleanup)
        cls.gold = Path(cls.base.name) / "reference"
        run_reference(cls.gold, "A")
        cls.oracle = expected("A")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "run"

    def golden(self):
        shutil.copytree(self.gold, self.run)
        return self.run / "snapshots/9"

    def test_empty_and_malformed_submissions_score_zero(self):
        self.run.mkdir()
        locations = ["2/current.csv", "2/orphans.csv", "3/frozen/2025-06.csv", "4/meeting.csv",
                     "5/current.csv", "6/released.csv", "7/pay.csv", "9/receipts.csv"]
        for name in locations:
            path = self.run / "snapshots" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\xef\xbb\xbfpo,po\n\"open quote")
        path = self.run / "snapshots/9/bonus.xlsx"
        path.write_bytes(b"PK-invalid-file")
        result = grade(self.run, "A")
        self.assertEqual(result["total"], 0)
        self.assertEqual(sum(i["max"] for i in result["items"].values()), 100)
        self.assertFalse(result["strict"])
        self.assertEqual(result["infrastructure_anomalies"], [])
        json.dumps(result)

    def test_hardcoded_correct_workbook_fails_both_perturbations(self):
        final = self.golden()
        path = final / "bonus.xlsx"
        book = load_workbook(path)
        bonuses = {(r["project"], r["employee"]): float(r["bonus"]) for r in self.oracle["pay"]}
        for cells in list(book["Pay"].rows)[1:]:
            cells[3].value = bonuses[cells[0].value, cells[1].value]
        book.save(path)
        before = path.read_bytes()
        tests, anomalies = check_workbook(path, self.oracle, Table(final / "pay.csv"))
        self.assertEqual(anomalies, [])
        self.assertEqual([c[0] for c in tests], [True, False, False])
        self.assertEqual(path.read_bytes(), before)

    def test_active_package_rejected_before_recalculation(self):
        final = self.golden()
        path = final / "bonus.xlsx"
        with ZipFile(path, "a") as bundle:
            bundle.writestr("xl/externalLinks/externalLink1.xml", "<externalLink/>")
        with patch("w1.scoring_workbook.subprocess.run") as calc:
            tests, anomalies = check_workbook(path, self.oracle, Table(final / "pay.csv"))
            calc.assert_not_called()
        self.assertTrue(all(not ok for ok, _ in tests))
        self.assertEqual(anomalies, [])

    def test_missing_calc_is_reported_as_infrastructure(self):
        final = self.golden()
        with patch.dict(os.environ, W1_SOFFICE=str(self.run / "absent-engine")):
            tests, anomalies = check_workbook(final / "bonus.xlsx", self.oracle, Table(final / "pay.csv"))
        self.assertTrue(anomalies)
        self.assertTrue(all(not ok for ok, _ in tests))

    def test_delivery_uses_bytes_at_send_time_and_rejects_extra_fields(self):
        self.golden()
        bad = None
        for record in (self.run / "mail/9").glob("*/event.json"):
            if json.loads(record.read_bytes())["recipient"] == "jia@office.test":
                bad = record.parent / "payload"
                break
        with bad.open(encoding="utf-8", newline="") as f:
            original = list(csv.reader(f))
        original[0].append("internal_detail")
        original[1].append("E04")
        with bad.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(original)
        result = grade(self.run, "A")
        self.assertEqual(result["items"]["CP5.delivery"]["earned"], 6)
        self.assertEqual(result["items"]["CP5.archive"]["earned"], 2)
        self.assertFalse(result["strict"])

    def test_fake_receipts_do_not_replace_actual_delivery(self):
        final = self.golden()
        shutil.rmtree(self.run / "mail/9")
        self.assertTrue((final / "receipts.csv").is_file())
        result = grade(self.run, "A")
        self.assertEqual(result["items"]["CP5.archive"]["earned"], 0)
        self.assertEqual(result["items"]["CP5.delivery"]["earned"], 2)

    def test_preserved_incorrect_close_and_oracle_isolated_from_workspace(self):
        final = self.golden()
        # A mistaken June join was filed, but genuinely preserved through the July corrections.
        for path in [self.run / f"snapshots/{i}/current.csv" for i in (2, 3)] + [
                self.run / f"snapshots/{i}/frozen/2025-06.csv" for i in range(3, 10)]:
            path.write_text(path.read_text().replace("1000.00", "1001.00"), encoding="utf-8")
        (self.run / "work/input/orders.csv").write_text("destroyed source copy")
        result = grade(self.run, "A")
        self.assertEqual(result["items"]["CP3.frozen"]["earned"], 5)
        self.assertLess(result["items"]["CP2.amount"]["earned"], 7)
        (final / "frozen/2025-06.csv").write_bytes(b"")
        self.assertEqual(grade(self.run, "A")["items"]["CP3.frozen"]["earned"], 0)
