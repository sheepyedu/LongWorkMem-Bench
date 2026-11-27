import csv
import shutil
import tempfile
import unittest
from functools import partial
from pathlib import Path

from openpyxl import load_workbook

from w1.reference import run_reference, solve_turn


def write_table(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def read_table(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class ReferenceBusinessRulesTest(unittest.TestCase):
    def test_june_and_july_keep_separate_receipt_histories(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            inputs = work / "input"
            write_table(inputs / "orders.csv", ("po", "line", "project", "ordered", "unit_price"),
                        [("PO-X", "01", "甲", 10, "2.25"), ("PO-Y", "01", "乙", 1, "3.00")])
            header = ("event", "po", "line", "date", "qty")
            receipt = ("receive-X", "PO-X", "01", "2025-06-12", 10)
            write_table(inputs / "receipts_june.csv", header,
                        [receipt, ("receive-Y", "PO-Y", "01", "2025-06-10", 1),
                         ("july-9-Y", "PO-Y", "01", "2025-07-09", 5)])
            write_table(inputs / "invoices.csv", ("invoice_line", "po", "line", "qty", "amount"),
                        [("bill-X", "PO-X", "01", 10, "22.50"), ("bill-Y", "PO-Y", "01", 1, "3.00"),
                         ("orphan", "PO-Z", "01", 1, "3.00")])
            solve_turn(work, 1)
            write_table(inputs / "receipts_amend.csv", header,
                        [receipt, ("return-X", "PO-X", "01", "2025-06-20", -2)])
            for turn in (2, 3, 4):
                solve_turn(work, turn)
            frozen_path = work / "out/frozen/2025-06.csv"
            frozen = frozen_path.read_bytes()
            june = {row["po"]: row for row in read_table(frozen_path)}
            self.assertEqual((june["PO-X"]["net"], june["PO-X"]["flags"]), ("8", "QA"))
            self.assertEqual(june["PO-Y"]["flags"], "")
            self.assertEqual(read_table(work / "out/orphans.csv")[0]["id"], "orphan")
            meeting, = read_table(work / "out/meeting.csv")
            self.assertEqual([meeting[key] for key in ("exception_lines", "qty_lines",
                                                       "amount_lines", "orphan_events")],
                             ["1", "1", "1", "1"])
            write_table(inputs / "receipts_july.csv", header,
                        [("receive-X-late", "PO-X", "01", "2025-07-08", 2)])
            write_table(inputs / "invoices_july.csv", ("invoice_line", "po", "line", "qty", "amount"),
                        [("bill-X", "PO-X", "01", 10, "22.50"), ("credit-Y", "PO-Y", "01", 0, "-3.00")])
            solve_turn(work, 5)
            july = {row["po"]: row for row in read_table(work / "out/current.csv")}
            self.assertEqual((july["PO-X"]["net"], july["PO-X"]["flags"]), ("10", ""))
            self.assertEqual((july["PO-Y"]["net"], july["PO-Y"]["flags"], july["PO-Y"]["amount_diff"]),
                             ("1", "A", "-3.00"))
            self.assertEqual(frozen_path.read_bytes(), frozen)


def reformat_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = list(reversed(reader.fieldnames))
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(reversed(rows))


class GradedWalkthroughTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        cls.root = Path(folder.name)
        for variant in ("A", "B"):
            run_reference(cls.root / variant, variant)

    def test_reference_both_variants_score_full_and_change_only_pay_assignment(self):
        from w1.grade import grade

        for variant in ("A", "B"):
            with self.subTest(variant=variant):
                result = grade(self.root / variant, variant)
                self.assertEqual(result["infrastructure_anomalies"], [])
                self.assertEqual(result["total"], 100, result["items"])
                self.assertTrue(result["strict"])
        outputs = [self.root / v / "snapshots/9" for v in ("A", "B")]
        for name in ("current.csv", "frozen/2025-06.csv", "meeting.csv", "released.csv"):
            self.assertEqual(*(read_table(out / name) for out in outputs))
        pays = [read_table(out / "pay.csv") for out in outputs]
        self.assertNotEqual(*pays)

    def candidate(self, name, after_turn):
        """Submit artifacts and mailbox actions before the controller freezes each turn."""
        from w1 import mail, runstate, world
        from w1.grade import grade

        run = self.root / name
        work = runstate.prepare(run)
        for turn in range(1, 10):
            world.release(work, turn, "A")
            act = partial(mail.act, run, turn)
            solve_turn(work, turn, mail=act)
            after_turn(work, turn, act)
            runstate.freeze(run, turn)
        return grade(run, "A")

    def test_equivalent_files_and_formula_still_score_full(self):
        def equivalent(work, turn, act):
            out = work / "out"
            if turn in (1, 2, 5):
                reformat_csv(out / "current.csv")
                reformat_csv(out / "orphans.csv")
            if turn == 7:
                reformat_csv(out / "pay.csv")
                book = load_workbook(out / "bonus.xlsx")
                sheet = book["Pay"]
                for cell in list(sheet.columns)[3][1:]:
                    cell.value = f"=ROUND({cell.value[1:]},2)"
                    cell.number_format = "#,##0.00"
                book.save(out / "bonus.xlsx")
                book.close()

        result = self.candidate("equivalent", equivalent)
        self.assertEqual(result["total"], 100, result["items"])
        self.assertTrue(result["strict"])

    def test_using_august_transfer_in_july_fails_at_assignment(self):
        def mistaken_assignment(work, turn, act):
            if turn == 7:
                for name in ("pay.csv", "bonus.xlsx"):
                    shutil.copyfile(self.root / "B/snapshots/7" / name, work / "out" / name)

        result = self.candidate("late-transfer", mistaken_assignment)
        self.assertFalse(result["strict"])
        items = result["items"]
        self.assertLess(items["CP4.scope"]["earned"], items["CP4.scope"]["max"])
        for item in ("CP3.current", "CP3.frozen", "CP4.split", "CP4.residual"):
            self.assertEqual(items[item]["earned"], items[item]["max"], item)

    def test_archive_preserving_an_incorrect_copy_of_the_closed_ledger(self):
        def wrong_copy(work, turn, act):
            if turn == 3:
                path = work / "out/frozen/2025-06.csv"
                rows = read_table(path)
                rows[0]["invoiced_qty"] = str(int(rows[0]["invoiced_qty"]) + 1)
                fields = list(rows[0])
                write_table(path, fields, ([row[k] for k in fields] for row in rows))

        result = self.candidate("bad-freeze", wrong_copy)
        self.assertFalse(result["strict"])
        frozen = result["items"]["CP3.frozen"]
        self.assertLess(frozen["earned"], frozen["max"])

    def test_early_send_is_remembered_after_correct_final_delivery(self):
        def early_send(work, turn, act):
            if turn == 8:
                act("deliver", "jia@office.test", "out/pay.csv", "七月奖金明细")

        result = self.candidate("early-send", early_send)
        self.assertFalse(result["strict"])
        delivery = result["items"]["CP5.delivery"]
        self.assertLess(delivery["earned"], delivery["max"])
        for item, details in result["items"].items():
            if item.startswith(("CP1", "CP2", "CP3", "CP4")):
                self.assertEqual(details["earned"], details["max"], item)
