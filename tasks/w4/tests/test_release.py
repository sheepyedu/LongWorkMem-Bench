import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import load_workbook
from tasks.w1.runstate import prepare, freeze
from tasks.w4 import grade as grader
from tasks.w4.office import invoke, status
from tasks.w4.scenario import (
    init,
    release,
    CODES,
    FIRST,
    NEW,
    LAST,
    TABS,
    ROUNDS,
    object_id,
    address,
)


def fixture(root, mode="gold"):
    work = prepare(root)
    init(work)
    wb = load_workbook(work / "out/交接.xlsx")

    def row(tab, *v):
        wb[tab].append(list(v))

    def send(k, i, s, days, mail, action="deliver", unit="工作日"):
        text = f"对象：{object_id(i, s)}\n换机时限: {days}个{unit}\n"
        (work / "out/manual.md").write_text(text)
        return invoke(
            root,
            t,
            None,
            action,
            dict(subject=k, recipient=mail, attachment="out/manual.md"),
        )

    # Authored from the public case file. Keep the expected answer independent of the grader.
    firstdays = [7, 10, 10, 5, 10, 10, 10, 10, 10, 10, 10, 10]
    for t in ROUNDS:
        release(work, t)
        if t == 1:
            for n, (_, i, s) in enumerate(FIRST):
                row("期初", object_id(i, s), f"05-{i + 1:02}-{n % 2 + 1}")
            for k, st, a in [
                ("L01", "已确认", "勘误"),
                ("L02", "退信", "重投"),
                ("L03", "待确认", "跟进"),
                ("L04", "已确认", "关闭"),
            ]:
                row("待办", k, st, a)
        if t == 2:
            for obj, v in [("HZ-A", "采用"), ("JL-B", "采用"), ("QH-A", "待签")]:
                row("变更", obj, v)
            for n in (0, 1, 3, 8):
                k, i, s = FIRST[n]
                send(k, i, s, firstdays[n], address(i), "draft")
        if t == 3:
            for n, (k, i, s) in enumerate(FIRST):
                if k in ("P08", "P12"):
                    continue
                send(
                    k,
                    i,
                    s,
                    firstdays[n],
                    address(i),
                    unit="自然日" if mode == "recover" and n == 0 else "工作日",
                )
        if t == 4:
            for k, _, _ in FIRST:
                st = "已确认"
                if k in ("P08", "P12"):
                    st = "未发"
                if k in ("P03", "P09"):
                    st = "退信"
                if k == "P01":
                    st = "待确认"
                row("回执", k, st)
            for k, i, s, n in [
                ("P03-R", 1, "A", 10),
                ("P09-R", 4, "A", 10),
                ("L01-R", 0, "A", 7),
                ("L02-R", 1, "B", 5),
            ]:
                send(k, i, s, n, address(i, "backup"))
        if t == 5:
            for i in (0, 1):
                row(
                    "通讯",
                    CODES[i],
                    address(i, "new"),
                    address(i),
                    address(i, "review"),
                )
        if t == 6:
            for (k, i, s), n in zip(NEW, [7, 10, 5, 10]):
                send(k, i, s, n, address(i, "new") if i < 2 else address(i))
        if t == 7:
            for o, d, a in [
                ("HZ-A", "6月10日", "切换"),
                ("JL-B", "10", "切换"),
                ("QH-A", "待定", "待签"),
            ]:
                row("排期", o, d, a)
        if t == 8:
            row("值班", "东台", "赵宁")
            row("值班", "西台", "吴禾")
        if t == 9:
            for (k, i, s), n in zip(LAST, [7, 5, 10]):
                send(k, i, s, n, address(i, "new") if i < 2 else address(i))
        if t == 10:
            send("U01", 0, "A", 10, address(0, "new"))
            send("U04", 1, "B", 8, address(1, "new"))
        if t == 11:
            for n, ack, new in [
                (0, 0, 10),
                (1, 1, 10),
                (3, 1, 8),
                (4, 1, 10),
                (8, 0, 10),
                (9, 1, 10),
            ]:
                k, i, s = FIRST[n]
                old = str(firstdays[n]) + "个工作日"
                actual = "7个自然日" if mode == "recover" and n == 0 else old
                row("追溯", k, old, actual, ack, str(new) + "个工作日")
            send("L03-C", 2, "A", 10, address(2))
            if mode == "recover":
                send("P01-C", 0, "A", 10, address(0, "review"))
        if t == 12:
            for k, i in [
                ("P01", 0),
                ("P03", 1),
                ("P03-R", 1),
                ("L01-R", 0),
                ("L02-R", 1),
                ("N01", 0),
                ("N03", 1),
                ("T01", 0),
                ("U01", 0),
                ("U04", 1),
                ("L03-C", 2),
            ]:
                failed = k == "P03"
                row(
                    "交割",
                    k,
                    "退信" if failed else "已确认",
                    "重投" if failed else "关闭",
                    address(i, "new") if failed else address(i),
                )
        wb.save(work / "out/交接.xlsx")
        freeze(root, t, rounds=ROUNDS)
    wb.close()


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / "run"

    def test_gold_scores_and_future_cut(self):
        fixture(self.run)
        result = grader.grade(self.run)
        self.assertEqual(result["rounds"], list(grader.POINTS))
        self.assertEqual(result, grader.grade(self.run))
        self.assertEqual(result["delayed_retention"], dict(correct=4, eligible=4))
        with self.assertRaises(ValueError):
            invoke(
                self.run, 4, None, "receipt_query", dict(case="", as_of="5", receipt="")
            )
        e = invoke(
            self.run, 12, None, "receipt_query", dict(case="P01", as_of="4", receipt="")
        )[0]
        self.assertEqual(e["status"], "待确认")
        for i in range(1, 13):
            (self.run / "snapshots" / str(i) / "交接.xlsx").write_bytes(b"bad")
        result = grader.grade(self.run)
        self.assertEqual(len(result["format_issues"]), 12)

    def test_wrong_unit_recovers_without_cascade(self):
        fixture(self.run, "recover")
        result = grader.grade(self.run)
        self.assertLess(result["rounds"][2], 13)
        self.assertEqual(result["rounds"][10], 17)
        self.assertEqual(result["delayed_retention"], dict(correct=3, eligible=3))

    def test_empty_and_missing_evidence(self):
        prepare(self.run)
        for t in ROUNDS:
            freeze(self.run, t, rounds=ROUNDS)
        self.assertEqual(grader.grade(self.run)["total"], 0)
        shutil.rmtree(self.run / "snapshots/8")
        with self.assertRaises(ValueError):
            grader.grade(self.run)

    def test_manual(self):
        self.assertEqual(
            grader.manual("对象：HZ-A\n换机时限：七 个 工作日".encode()),
            ("HZ-A", "7个工作日"),
        )
        self.assertEqual(
            grader.manual(
                "对象：HZ-A\n换机时限：7个工作日\n换机时限：10个工作日".encode()
            )[1],
            "条款无效",
        )
