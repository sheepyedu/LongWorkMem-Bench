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

    def test_unapproved_project_in_early_official_release(self):
        self.golden()
        (self.run / "snapshots/5/released.csv").write_text("project,pool\n丙,3000.00\n")
        result = grade(self.run, "A")
        self.assertEqual(result["items"]["CP3.release"]["earned"], 4)
        self.assertFalse(result["strict"])

    def test_hr_dependency_includes_e07_payroll_outcome(self):
        self.golden()
        path = self.run / "snapshots/7/pay.csv"
        path.write_text(path.read_text().replace("689.65", "0.00"))
        result = grade(self.run, "A")
        self.assertEqual(result["items"]["CP4.scope"]["earned"], 10)
        self.assertFalse(result["dependencies"]["HR-0628"]["passed"])

    def test_unrelated_draft_is_separate_from_bonus_drafts(self):
        from w1.mail import act
        self.golden()
        act(self.run, 1, "draft", "ap@office.test", "out/orphans.csv", "请协助认领发票")
        result = grade(self.run, "A")
        self.assertEqual(result["total"], 100)
        self.assertEqual(result["incidental_drafts"][0]["recipient"], "ap@office.test")

    def test_project_subject_accepts_contract_language_and_rejects_real_leak(self):
        from w1.scoring_mail import check_mail
        final = self.golden()
        for subject, credit in [("乙项目七月奖，供甲方备案", 7), ("乙项目七月奖，附甲项目奖金10000.01元", 6),
                                ("乙项目七月奖，E07工时4小时", 6)]:
            for path in (self.run / "mail").glob("*/*/event.json"):
                entry = json.loads(path.read_bytes())
                if entry["recipient"] == "yi@office.test":
                    entry["subject"] = subject
                    path.write_text(json.dumps(entry))
            evidence, *_ = check_mail(self.run, final, self.oracle)
            self.assertEqual(sum(w for w, (ok, _) in evidence if ok), credit, subject)

    def test_sparse_oversized_helper_blocked_before_calc(self):
        final = self.golden()
        path = final / "bonus.xlsx"
        book = load_workbook(path)
        book.create_sheet("Helper")["XFD65535"] = "outside data bounds"
        book.save(path)
        with patch("w1.scoring_workbook.subprocess.run") as engine:
            checks, _ = check_workbook(path, self.oracle, Table(final / "pay.csv"))
            engine.assert_not_called()
            self.assertTrue(all(not ok for ok, _ in checks))

    def test_dedup_separates_equal_receipts_and_orphan_source_ids(self):
        self.golden()
        rows = self.run / "snapshots/2/current.csv"
        with rows.open(newline="") as f:
            records = list(csv.DictReader(f))
        for row in records:
            if (row["po"], row["line"]) == ("PO-215", "1"):
                row["net"] = str(int(row["net"]) // 2)
        with rows.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=records[0])
            w.writeheader()
            w.writerows(records)
        orphan = self.run / "snapshots/2/orphans.csv"
        header, one, two = orphan.read_text().splitlines()
        orphan.write_text("\n".join([header, one, one]) + "\n")
        result = grade(self.run, "A")
        self.assertEqual(result["items"]["CP1.dedup"]["earned"], 0)
        self.assertEqual(result["items"]["CP1.orphans"]["earned"], 0)

    def test_grouped_decimal_csv_and_invalid_grouping(self):
        path = Path(self.tmp.name) / "currency.csv"
        for amount, ok in [("10,000.01", True), ("10,00.01", False), ("10,0,0,0.01", False)]:
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["pool"])
                writer.writerow([amount])
            self.assertEqual(Table(path).matches([{"pool": "10000.01"}], "pool")[0], ok, amount)

    def test_merged_cell_area_limited_before_openpyxl_expands_it(self):
        from w1.scoring_tables import InvalidArtifact
        from w1.scoring_workbook import inspect_package
        path = Path(self.tmp.name) / "wide-merge.xlsx"
        with ZipFile(path, "w") as bundle:
            bundle.writestr("xl/worksheets/sheet3.xml",
                            '<worksheet><mergeCells><mergeCell ref="A1:IV4096"/></mergeCells></worksheet>')
        with self.assertRaises(InvalidArtifact):
            inspect_package(path)
