"""Gold answers from the public queue, correspondence and follow-up orders."""

import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from openpyxl import load_workbook

from tasks.w4 import annex, night
from tasks.w4.grade import grade
from tasks.w4.office import attachment, events, invoke
from tasks.w4.scenario import init, release
from .test_release import fixture
from .test_annex import play

# Ordered by customer and series. Never derive expected outcomes with the grader.
ORIGINAL = [8, 4, 5, 5, 3, 7, 4, 6, 5, 4, 6, 5]
CURRENT = [4, 4, 5, 0, 3, 7, 4, 6, 7, 4, 6, 5]
CUT = [
    "确认",
    "待确认",
    "确认",
    "退信",
    "未发",
    "退信",
    "确认",
    "未发",
    "待确认",
    "待确认",
    "确认",
    "待确认",
]
ACTIONS = [
    "关闭",
    "关闭",
    "勘误",
    "暂缓",
    "首发",
    "重投",
    "关闭",
    "首发",
    "关闭",
    "勘误",
    "关闭",
    "跟进",
]
DEST = {
    "H03": "jl.review",
    "H05": "np.service",
    "H06": "np.backup",
    "H08": "yc.service",
    "H10": "qh.service",
}


def book_at(root, template, t):
    wb = load_workbook(template)
    ws = wb["队列"]
    cap = {8: [8, 7, 6, 6], 9: [5, 7, 6, 9], 12: [5, 5, 8, 9]}[t]
    for i, n in enumerate(cap, 2):
        wb["容量"].cell(i, 2, n)
    offsets = {}
    for e in events(root, 3):
        if e["subject"] in ("P03", "P09"):
            continue
        value = int(re.search(r"预留席位：(\d+)", attachment(root, e).decode())[1])
        offsets[e["subject"]] = offsets.get(e["subject"], 0) + value
    for i, k in enumerate(night.QUEUE, 2):
        j = night.IDS.index(k)
        d = max(
            0,
            (CURRENT if t == 12 else ORIGINAL)[j]
            - offsets.get("P" + k[1:], 0)
            - (2 if t == 12 and k == "H08" else 0),
        )
        if (t >= 9 and k == "H03") or (t == 12 and k == "H07"):
            d = 0
        ws.cell(i, 3, d)
        previous = "0" if i == 2 else f"SUMIF(B$2:B{i - 1},B{i},D$2:D{i - 1})"
        ws.cell(i, 4, f"=MIN(C{i},MAX(0,VLOOKUP(B{i},容量!A$2:B$5,2,0)-{previous}))")
        ws.cell(i, 5, f"=C{i}-D{i}")
    wb.save(root / "snapshots" / str(t) / "夜班预约.xlsx")
    wb.close()


def gold(root):
    fixture(root / "base")
    run = root / "gold"
    play(run, root / "base")
    (run / "manifest.json").write_text('{"protocol":"w4-release-v3"}')
    night.initialize(run / "work")
    for t in (8, 9, 12):
        book_at(run, run / "work/out/夜班预约.xlsx", t)
    receipts = {}
    for k, mail in DEST.items():
        j = night.IDS.index(k)
        (run / "work/out/night.md").write_text(
            f"对象：{night.obj(k)}\n处置：{ACTIONS[j]}\n夜班额度：{CURRENT[j]}\n"
        )
        receipts[k] = invoke(
            run,
            11,
            None,
            "deliver",
            dict(recipient=mail + "@office.test", subject=k, attachment="out/night.md"),
        )["receipt"]
    for t, tab in [(11, "夜班异议"), (12, "夜班结班")]:
        p = run / "snapshots" / str(t) / "交接.xlsx"
        wb = load_workbook(p)
        ws = wb.create_sheet(tab)
        ws.append(night.HISTORY[tab])
        for j, k in enumerate(night.IDS):
            if t == 11:
                ws.append(
                    [
                        k,
                        ORIGINAL[j],
                        night.OLD[j] if night.OLD[j] is not None else "未发",
                        CUT[j],
                        CURRENT[j],
                        ACTIONS[j],
                    ]
                )
            else:
                ws.append(
                    [
                        k,
                        int(k in receipts),
                        receipts.get(k, "无"),
                        "已确认" if k in receipts else "未发",
                    ]
                )
        wb.save(p)
        wb.close()
    return run


class NightCases(unittest.TestCase):
    def test_public_clock(self):
        with TemporaryDirectory() as tmp:
            from tasks.w1.runstate import prepare

            work = prepare(Path(tmp) / "clock")
            init(work)
            annex.initialize(work)
            night.initialize(work)
            for t in range(1, 13):
                release(work, t)
                annex.release(work, t)
                night.release(work, t)
                self.assertEqual(
                    (work / "inbox/06-02/夜班/当班签单.csv").exists(), t == 2
                )
                self.assertEqual(
                    (work / "inbox/06-07/夜班/当班签单.csv").exists(), t == 7
                )
                self.assertEqual(
                    (work / "inbox/06-07/夜班/客户回条.csv").exists(), t >= 7
                )

    @unittest.skipUnless(os.environ.get("W4_TEST_ROOT"), "requires W4 Calc Docker")
    def test_full_replay_and_static_handover(self):
        with TemporaryDirectory() as tmp:
            run = gold(Path(tmp))
            result = grade(run)
            self.assertEqual(
                result["total"],
                100,
                [
                    (g["group"], g["earned"], g["weight"])
                    for g in result["details"]
                    if abs(g["weight"] - g["earned"]) > 0.00001
                ],
            )
            # Correct cached numbers are insufficient when input cells change.
            row = next(
                g
                for g in result["details"]
                if g["turn"] == 8 and g["group"] == "夜班当日安排"
            )
            p = run / "snapshots/8/夜班预约.xlsx"
            wb = load_workbook(p)
            for i, k in enumerate(night.QUEUE, 2):
                x, y = row["evidence"]["scenarios"]["baseline"]["expected"][k]
                wb["队列"].cell(i, 4).value = x
                wb["队列"].cell(i, 5).value = y
            wb.save(p)
            wb.close()
            # Remove other handovers to exercise proper format loss, zipping remains host-only.
            for t in (9, 12):
                (run / "snapshots" / str(t) / "夜班预约.xlsx").unlink()
            replay = grade(run)
            self.assertEqual(replay["total"], 75)
