"""Build an independent gold appendix from the public case folders, using a paper ledger."""

import csv
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from openpyxl import load_workbook

from tasks.w1.runstate import prepare, freeze
from tasks.w4 import annex
from tasks.w4.grade import grade
from tasks.w4.office import events, invoke, status
from tasks.w4.scenario import ROUNDS, init, release, AUDITS
from .test_release import fixture


def records(p):
    with p.open() as f:
        return list(csv.DictReader(f))


def play(root, base, omit=False):
    work = prepare(root)
    init(work)
    annex.initialize(work)
    (root / "manifest.json").write_text('{"protocol":"w4-release-v2"}')
    stations = {
        r["对象"]: r["主站"] for r in records(work / "input/现场服务/站点底册.csv")
    }
    badges = {
        (r["主站"], r["服务类别"]): r["凭证"]
        for r in records(work / "input/现场服务/凭证册.csv")
    }
    limits = {
        r["主站"]: int(r["增额"]) for r in records(work / "input/现场服务/期初容量.csv")
    }
    approvals = []
    canceled = set()
    issued = []
    first = {}
    for t in ROUNDS:
        release(work, t)
        annex.release(work, t)
        batch = work / "inbox" / f"06-{t:02}"
        roster = batch / "值班签发名册.csv"
        if roster.exists():
            allowed = {r["对象"]: r["授权签发人"] for r in records(roster)}
            for p in (batch / "签署附件").rglob("*.txt"):
                obj, seq, _, kind, sign, lo, hi, site = re.fullmatch(
                    r"对象 (.+?)；签发流水 (\d+)；签署日 (\d+)；类别 (.+?)；签发人 (.+?)；有效期 第(\d+)日至第(\d+)日（含）；主站 (.+?)。",
                    p.read_text(),
                ).groups()
                if sign == allowed[obj] and kind == "正式":
                    approvals.append((int(lo), int(seq), int(hi), obj, site))
        if (batch / "撤单.csv").exists():
            canceled.update(int(r["原流水"]) for r in records(batch / "撤单.csv"))
        if (batch / "凭证修订.csv").exists():
            for r in records(batch / "凭证修订.csv"):
                badges[r["主站"], r["服务类别"]] = r["新凭证"]
        if (batch / "新增席位.csv").exists():
            for r in records(batch / "新增席位.csv"):
                limits[r["主站"]] += int(r["增额"])
        balances = limits.copy()
        for event, site, n in issued:
            if status(event, t) != "退信":
                balances[site] -= n
        plans = []
        devices = {}
        if (batch / "设备申请.csv").exists():
            for r in sorted(
                records(batch / "设备申请.csv"), key=lambda r: int(r["修订号"])
            ):
                devices[r["案号"], r["设备序号"]] = r
        batch_mail = [e for e in events(base, t, None) if e["turn"] == t]
        for e in batch_mail:
            k = e["subject"]
            request = [r for (case, _), r in devices.items() if case == k]
            demand = sum(int(r["申请席位"]) for r in request if r["状态"] != "取消")
            source = (base / "mail" / str(t) / e["receipt"] / "payload").read_text()
            obj = re.search(r"对象：(.*)", source)[1]
            eligible = [
                a
                for a in approvals
                if a[0] <= t <= a[2] and a[3] == obj and a[1] not in canceled
            ]
            site = sorted(eligible)[-1][-1] if eligible else stations[obj]
            plans.append(
                (
                    int(request[0]["优先号"]),
                    k,
                    site,
                    badges[site, request[0]["服务类别"]],
                    demand,
                    source,
                    e,
                )
            )
        for _, k, site, badge, demand, src, e in sorted(plans):
            n = demand if demand <= balances[site] else 0
            balances[site] -= n
            text = (
                src
                if omit
                else src + f"\n服务主站：{site}\n服务凭证：{badge}\n预留席位：{n}\n"
            )
            (work / "out/manual.md").write_text(text)
            res = invoke(
                root,
                t,
                None,
                e["action"],
                dict(subject=k, recipient=e["recipient"], attachment="out/manual.md"),
            )
            if e["action"] == "deliver":
                event = next(
                    x for x in events(root, t) if x["receipt"] == res["receipt"]
                )
                if not omit:
                    issued.append((event, site, n))
                if t == 3:
                    first[k] = (site, badge, n)
        book = load_workbook(base / "snapshots" / str(t) / "交接.xlsx")
        for sheet, headers in annex.EXTRA_TABS.items():
            book.create_sheet(sheet).append(headers)
        if t == 11:
            for k in AUDITS:
                site, badge, n = first[k]
                book["附页追溯"].append([k, site, badge, n, n, 0 if k == "P09" else n])
        if t == 12:
            for site, bal in balances.items():
                book["席位交割"].append([site, limits[site] - bal, bal])
        book.save(work / "out/交接.xlsx")
        book.close()
        freeze(root, t, rounds=ROUNDS)


class FieldTest(unittest.TestCase):
    def test_independent_reference_and_missing_appendix(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            fixture(root / "base")
            play(root / "hard", root / "base")
            g = grade(root / "hard")
            self.assertEqual(g["total"], 100)
            self.assertEqual(g["rounds"], [5, 6, 13, 10, 3, 11, 4, 2, 9, 14, 17, 6])
            play(root / "missing", root / "base", omit=True)
            self.assertLess(grade(root / "missing")["total"], 70)
            day = invoke(
                root / "hard",
                12,
                None,
                "receipt_query",
                dict(case="P01", as_of="06-04", receipt=""),
            )
            self.assertEqual(day[0]["status"], "待确认")
            invoke(
                root / "hard",
                6,
                None,
                "deliver",
                dict(
                    subject="bad",
                    recipient="qh.new@office.test",
                    attachment="out/manual.md",
                ),
            )
            got = invoke(
                root / "hard",
                12,
                None,
                "receipt_query",
                dict(case="bad", as_of="6月7日", receipt=""),
            )
            self.assertEqual(got[0]["status"], "退信")
