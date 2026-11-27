import csv
from collections import Counter
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1.world import release


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


class WorldTests(unittest.TestCase):
    def test_scheduled_releases_and_only_one_changed_fact(self):
        with TemporaryDirectory() as tmp:
            worlds = [Path(tmp) / name for name in ("A", "B")]
            changed_paths = set()
            changed_lines = []
            for turn in range(1, 10):
                prompts = [release(path, turn, path.name) for path in worlds]
                self.assertEqual(prompts[0], prompts[1])
                files = [{p.relative_to(w): p.read_bytes() for p in w.rglob("*") if p.is_file()}
                         for w in worlds]
                self.assertEqual(files[0].keys(), files[1].keys())
                changed_paths = {p for p, data in files[0].items() if files[1][p] != data}
                expected = {Path("inbox/HR-0628.eml")} if turn >= 2 else set()
                self.assertEqual(changed_paths, expected)
                for filename, at_turn in [("receipts_amend.csv", 2), ("receipts_july.csv", 5),
                                          ("invoices_july.csv", 5), ("releases.csv", 6), ("hours.csv", 7)]:
                    self.assertEqual(Path("input", filename) in files[0], turn >= at_turn)
                if turn == 2:
                    mail = Path("inbox/HR-0628.eml")
                    bodies = [BytesParser(policy=policy.default).parsebytes(f[mail]).get_content()
                              for f in files]
                    changed_lines = [(a, b) for a, b in zip(*[s.splitlines() for s in bodies]) if a != b]
            self.assertEqual(changed_lines, [("批准生效日：2025-07-01", "批准生效日：2025-08-01")])
            root = worlds[0]
            self.assertIn(len([p for p in (root / "input").rglob("*") if p.is_file()]), range(80, 121))
            self.assertIn(len(list((root / "inbox").glob("*.eml"))), range(100, 201))
            self.assertFalse(list((root / "out").rglob("*")))

    def test_current_office_files_and_prior_distribution(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            release(root, 1, "A")
            admin = root / "input/综合办公室/2025-06"
            self.assertGreaterEqual(len([p for p in admin.rglob("*") if p.is_file()]), 6)
            for file in ("TR-0626", "IT-0627", "AD-0625"):
                self.assertTrue((root / "inbox" / f"{file}.eml").is_file())
            prior = read_rows(root / "input/archive/2025-05/甲项目/jia.csv")
            self.assertEqual([(r["project"], r["period"]) for r in prior], [("甲", "2025-05")])

    def test_june_close_and_july_posting(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for turn in range(1, 10):
                release(root, turn, "A")
            data = root / "input"
            order = next(r for r in read_rows(data / "orders.csv") if (r["po"], r["line"]) == ("PO-217", "1"))
            self.assertEqual((int(order["ordered"]), float(order["unit_price"])), (100, 100))
            receipts = {}
            seen = Counter()
            for name, expected in [("june", 95), ("amend", 90), ("july", 100)]:
                for row in read_rows(data / f"receipts_{name}.csv"):
                    seen[row["event"]] += 1
                    if row["event"] in receipts:
                        self.assertEqual(receipts[row["event"]], row)
                    receipts[row["event"]] = row
                total = sum(int(r["qty"]) for r in receipts.values()
                            if (r["po"], r["line"]) == ("PO-217", "1"))
                self.assertEqual(total, expected)
            self.assertGreater(max(seen.values()), 1)
            self.assertTrue(any(r["project"] == "共享" and r["employee"] == "E07"
                                for r in read_rows(data / "hours.csv")))

    def test_pending_project_is_reconciled_before_settlement(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for turn in range(1, 7):
                release(root, turn, "A")
            data = root / "input"
            orders = [row for row in read_rows(data / "orders.csv") if row["project"] == "丙"]
            receipts = {row["event"]: row for path in data.glob("receipts_*.csv") for row in read_rows(path)}
            invoices = [row for path in data.glob("invoices*.csv") for row in read_rows(path)]
            self.assertTrue(orders)
            for order in orders:
                key = (order["po"], order["line"])
                net = sum(int(r["qty"]) for r in receipts.values() if (r["po"], r["line"]) == key)
                amount = sum(Decimal(r["amount"]) for r in invoices if (r["po"], r["line"]) == key)
                self.assertEqual(net, int(order["ordered"]))
                self.assertEqual(amount, net * Decimal(order["unit_price"]))
            approved = [r["project"] for r in read_rows(data / "releases.csv") if r["status"] == "已放行"]
            self.assertNotIn("丙", approved)

    def test_can_retry_without_losing_outputs_or_releasing_later_inputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            release(root, 1, "A")
            report = root / "out" / "note.txt"
            report.write_text("记账中", encoding="utf-8")
            files = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            release(root, 1, "A")
            self.assertEqual(files, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()})
            for turn, variant in [(0, "A"), (10, "A"), (1, "X")]:
                with self.assertRaises(ValueError):
                    release(root, turn, variant)
