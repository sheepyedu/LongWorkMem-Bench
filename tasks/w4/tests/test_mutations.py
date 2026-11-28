"""Freeze normal and deliberately wrong work, then replay the same evidence."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
import shutil

from openpyxl import load_workbook
from tasks.w4.grade import grade, sheets
from tasks.w4.tests.test_release import fixture


class Mutations(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "run"
        fixture(self.root)

    def test_row_and_header_permutation(self):
        path = self.root / "snapshots/12/交接.xlsx"
        wb = load_workbook(path)
        rows = list(wb["交割"].values)
        del wb["交割"]
        ws = wb.create_sheet("交割")
        for r in [rows[0], *reversed(rows[1:])]:
            ws.append(list(reversed(r)))
        wb.save(path)
        wb.close()
        self.assertEqual(grade(self.root)["total"], 100)

    def test_duplicate_records_and_temporal_errors(self):
        path = self.root / "snapshots/11/交接.xlsx"
        wb = load_workbook(path)
        ws = wb["追溯"]
        # June 5 confirmation does not prove June 4 confirmation.
        ws["D2"] = 1
        wb.save(path)
        wb.close()
        g = grade(self.root)
        self.assertEqual(g["rounds"][10], 16.5)
        path = self.root / "snapshots/5/交接.xlsx"
        wb = load_workbook(path)
        ws = wb["通讯"]
        ws.append(list(ws.values)[1])
        wb.save(path)
        wb.close()
        self.assertLess(grade(self.root)["rounds"][4], 3)

    def test_repeated_real_dispatch_and_no_cross_round_rewrite(self):
        first = next(
            p
            for p in (self.root / "mail/3").glob("*/event.json")
            if json.loads(p.read_text())["subject"] == "P01"
        )
        copy = first.parent.parent / "M-duplicate"
        shutil.copytree(first.parent, copy)
        e = json.loads(first.read_text())
        e.update(receipt=copy.name, sequence=999)
        (copy / "event.json").write_text(json.dumps(e))
        # Independently edit the local working draft, never the frozen mail.
        (self.root / "work/out/manual.md").write_text("换机时限：200个工作日")
        g = grade(self.root)
        self.assertLess(g["rounds"][2], 13)
        self.assertLess(g["rounds"][10], 17)
        self.assertEqual(g["rounds"][9], 14)

    def test_wrong_file_types_and_lost_host_mail(self):
        from zipfile import ZipFile

        sample = self.root / "broken.xlsx"
        sample.mkdir()
        self.assertTrue(sheets(sample)[1])
        sample.rmdir()
        with ZipFile(sample, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            )
        self.assertTrue(sheets(sample)[1])
        shutil.rmtree(self.root / "mail")
        with self.assertRaises(ValueError):
            grade(self.root)
