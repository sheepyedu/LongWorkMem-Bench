import csv
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tasks.w1.runstate import prepare
from tasks.w4.quota import world
from tasks.w4.quota.desk import replay
from tasks.w4.quota.score import rows_at, score
from tasks.w4.office import invoke
from tasks.w4.tests.quota_controls import play


class QuotaTest(unittest.TestCase):
    def test_idempotent_rejection_and_protection(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "run"
            work = prepare(root)
            world.initialize(work)
            (root / "manifest.json").write_text('{"protocol":"w4-release-v4"}')

            def batch(rid, rev, n):
                p = work / "out/a.csv"
                p.write_text(f"案号,请求号,预期版本,目标席\nJ01,{rid},{rev},{n}\n")
                m = invoke(
                    root,
                    3,
                    None,
                    "deliver",
                    {
                        "subject": "站务申请",
                        "attachment": "out/a.csv",
                        "recipient": "quota@office.test",
                    },
                )
                return invoke(
                    root,
                    3,
                    None,
                    "receipt_query",
                    {"case": "", "as_of": "", "receipt": m["receipt"]},
                )[0]

            self.assertEqual(batch("a", 1, 0)["原因"], "承运回传")
            self.assertTrue(batch("a", 1, 0)["重复"])
            self.assertEqual(batch("a", 2, 0)["原因"], "请求号冲突")
            self.assertEqual(batch("b", 1, 0)["原因"], "版本已变")
            self.assertEqual(batch("c", 2, 0)["状态"], "部分受理")
            self.assertEqual(replay(root, 3)[0][3][1]["J01"]["实占"], 3)
            with self.assertRaises(ValueError):
                invoke(
                    root,
                    3,
                    None,
                    "receipt_query",
                    {"case": "", "as_of": "4", "receipt": ""},
                )

    def test_missing_column_and_duplicate_only_discard_affected_facts(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "接班.csv"
            p.write_text(
                "锁定,案号,原席\n2,J01,4\n1,J02,2\n3,J01,4\n", encoding="utf-8-sig"
            )
            x, issues = rows_at(p, world.FILES[1][1])
            self.assertEqual(x, {"J01": {}, "J02": {"原席": "2", "锁定": "1"}})
            self.assertIn("缺列或重复:章程额度", issues)

    @unittest.skipUnless(os.getenv("W4_TEST_ROOT"), "isolated Calc image required")
    def test_gold_and_single_cell_mutation(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "gold"
            play(root)
            g = score(root)
            self.assertEqual(g["total"], 100)
            self.assertLess(max(a["maximum"] for a in g["atoms"]), 0.6)
            p = root / "snapshots/10/调度.csv"
            data = list(csv.reader(p.read_text().splitlines()))
            data[1][data[0].index("兑入")] = "999"
            with p.open("w", newline="") as f:
                csv.writer(f).writerows(data)
            second = score(root)
            lost = [a["id"] for a in second["atoms"] if a["maximum"] != a["earned"]]
            self.assertEqual(lost, ["R10/J01/调度-兑入"])

    @unittest.skipUnless(os.getenv("W4_TEST_ROOT"), "isolated Calc image required")
    def test_compact_interface_and_early_customer_notice(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "gold"
            play(root, clarified=True)
            g = score(root)
            self.assertEqual((g["version"], g["total"]), ("release-v4.1", 100))
            from tasks.w4.office import events

            for e in events(root, 11):
                if e["turn"] == 11 and e["subject"] == "J02":
                    e["sequence"] = 0
                    (root / "mail/11" / e["receipt"] / "event.json").write_text(
                        json.dumps(e)
                    )
                    break
            lost = [
                x["id"] for x in score(root)["atoms"] if x["earned"] != x["maximum"]
            ]
            self.assertEqual(lost, ["R11/J02/办后才通知"])
            v = invoke(
                root,
                4,
                None,
                "receipt_query",
                dict(case="开班/变动", as_of="", receipt=""),
            )
            keys = [dict(zip(v["列"], row))["案号"] for row in v["行"]]
            self.assertEqual(keys, ["J01", "J07"])
            # A missing queue page must preserve independently verifiable station inputs.
            from openpyxl import load_workbook

            p = root / "snapshots/8/预约.xlsx"
            wb = load_workbook(p)
            del wb["队列"]
            wb.save(p)
            wb.close()
            g = score(root)
            capacity = [
                a
                for a in g["atoms"]
                if a["turn"] == 8 and a["field"] == "预约-可再分容量"
            ]
            self.assertEqual(len(capacity), 4)
            self.assertTrue(all(a["earned"] == a["maximum"] for a in capacity))
