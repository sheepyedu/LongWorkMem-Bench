"""Offline mutation controls for the W4 night handover. Requires the W4 Docker image."""

import json
import shutil
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from tasks.w1.runstate import freeze, prepare
from tasks.w4 import night
from tasks.w4.grade import grade
from tasks.w4.office import events, invoke
from tasks.w4.scenario import ROUNDS
from tasks.w4.tests.test_night import gold


def record(p):
    g = grade(p)
    return dict(
        total=g["total"],
        daytime=round(
            sum(x["earned"] for x in g["details"] if x["group"] == "日间履约"), 4
        ),
        night=[
            (r["group"], r["turn"], round(r["earned"], 4))
            for r in g["details"]
            if r["group"] != "日间履约"
        ],
    )


if __name__ == "__main__":
    res = {}
    with TemporaryDirectory() as td:
        root = Path(td)
        correct = gold(root)
        res["gold"] = record(correct)
        old = root / "v2"
        old.mkdir()
        with tarfile.open(
            Path(__file__).resolve().parents[3]
            / "rollout/w4/deepseek-v4.1-flash/v2/artifacts.tar.gz"
        ) as f:
            f.extractall(old, filter="data")
        (old / "manifest.json").write_text('{"protocol":"w4-release-v3"}')
        res["historical_v2_submission_without_v3_work"] = record(old)
        for mode in (
            "latest_only",
            "send_all",
            "static_all",
            "wrong_recipient",
            "empty",
        ):
            dest = root / mode
            if mode == "empty":
                prepare(dest)
                shutil.copy2(correct / "manifest.json", dest)
                for t in ROUNDS:
                    freeze(dest, t, rounds=ROUNDS)
            else:
                shutil.copytree(correct, dest)
            if mode == "latest_only":
                p = dest / "snapshots/11/交接.xlsx"
                w = load_workbook(p)
                s = w["夜班异议"]
                for r in range(2, 14):
                    s.cell(r, 2).value = s.cell(r, 5).value
                w.save(p)
                w.close()
            if mode in ("wrong_recipient", "send_all"):
                existing = {
                    e["subject"] for e in events(dest, 11) if e["subject"] in night.IDS
                }
                for k in night.IDS:
                    if mode == "send_all" and k not in existing:
                        invoke(
                            dest,
                            11,
                            None,
                            "deliver",
                            dict(
                                recipient="hz.service@office.test",
                                subject=k,
                                attachment="out/night.md",
                            ),
                        )
                if mode == "wrong_recipient":
                    for p in (dest / "mail/11").glob("*/event.json"):
                        e = json.loads(p.read_text())
                        if e["subject"] in night.IDS:
                            e.update(
                                recipient="wrong@office.test", unknown_mailbox=True
                            )
                            p.write_text(json.dumps(e))
            if mode == "static_all":
                goldresult = grade(correct)
                for x in goldresult["details"]:
                    if x["group"] != "夜班当日安排":
                        continue
                    p = dest / "snapshots" / str(x["turn"]) / "夜班预约.xlsx"
                    w = load_workbook(p)
                    s = w["队列"]
                    for i, k in enumerate(night.QUEUE, 2):
                        s.cell(i, 4).value, s.cell(i, 5).value = x["evidence"][
                            "scenarios"
                        ]["baseline"]["expected"][k]
                    w.save(p)
                    w.close()
            res[mode] = record(dest)
    print(json.dumps(res, ensure_ascii=False, indent=2))
