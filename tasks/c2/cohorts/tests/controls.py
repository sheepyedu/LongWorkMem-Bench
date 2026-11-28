"""Scripted integration trajectories using public inputs and native subscriber semantics."""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tasks.c1.runstate import freeze
from tasks.c2.evolution.tests.test_evolution import IMAGE, install_paging, run_cmd
from tasks.c2.scenario import write
from tasks.c2.subscriber import decode, receipts

from .. import runner
from ..grade import grade
from ..scenario import CHANNELS, MATERIAL_REVISION, SCORING_REVISION, VERSION


def ledger(run, t):
    archives = run / "work/input/vault"
    return {
        a: (
            json.loads((archives / f"{a}-closing-04.json").read_text())
            if t >= 5
            else []
        )
        + runner.online(run, t, a)
        for a in CHANNELS
    }


def drive(run, mode="reference"):
    work = run / "work"
    runner.setup(work)
    for t in range(1, 11):
        runner.release(run, t)
        if mode != "noop":
            if t == 1:
                install_paging(work / "project/portal.py")
            if t == 2:
                code = (
                    Path(__file__)
                    .resolve()
                    .parents[1]
                    .joinpath("reference.py")
                    .read_text()
                )
                original = code
                if mode == "latest-identity":
                    start = code.index("and datetime.fromisoformat(reg[")
                    end = code.index("\n        ):", start)
                    code = code[:start] + code[end:]
                if mode == "trust-stale-cache":
                    marker = "log, dest = map(Path, rest)"
                    code = code.replace(
                        marker,
                        marker
                        + '\n    if int(v)>=9:\n        cache=Path("data/receipt-cache.json")\n        log=Path("scratch/stale.json")\n        log.write_text(json.dumps(json.loads(cache.read_bytes())[a] if cache.is_file() else []))',
                    )
                if mode == "ignore-withdrawal":
                    code = code.replace('o["id"] not in revoked', "True")
                if mode == "fixed-ledger":
                    code = code.replace(
                        "by_account = json.loads(logs.read_text())",
                        'by_account = json.loads(Path("scratch/ledger.json").read_text())',
                    )
                if mode != "reference" and code == original:
                    raise ValueError("fault did not alter reference: " + mode)
                (work / "project/service.py").write_text(code)
            if t in (2, 3, 6, 7):
                run_cmd(work, "python3 project/service.py import input")
            if t == 5:
                result = []
                for q in json.loads((work / "input/support.json").read_bytes()):
                    items = json.loads(
                        run_cmd(
                            work, f"python3 project/service.py view {q['account']} 4"
                        )
                    )
                    r = next(
                        r
                        for r in items
                        if r["code"] == q["code"] and r["day"] == q["day"]
                    )
                    result.append(
                        dict(
                            q,
                            uid=r["uid"],
                            local=datetime.fromisoformat(r["utc"])
                            .astimezone(ZoneInfo("Europe/London"))
                            .strftime("%Y-%m-%d %H:%M"),
                        )
                    )
                write(work / "out/preview.json", result)
            if t in (4, 6, 7, 8, 9):
                known = ledger(run, t)
                for a in CHANNELS:
                    if t == 8 and a in "CD":
                        continue
                    write(work / "scratch/seen.json", known[a])
                    path = f"out/plan-{a}.ics" if t == 7 else f"out/dispatch-{a}.ics"
                    run_cmd(
                        work,
                        f"python3 project/service.py delta {a} {t} scratch/seen.json {path}",
                    )
                    payload = decode((work / path).read_bytes())
                    if payload and t != 7:
                        key = f"r{t}-{a}"
                        if t == 9 and a in ("C", "D") and len(payload) == 1:
                            incident = next(
                                r
                                for r in json.loads(
                                    (work / "input/timeouts.json").read_bytes()
                                )
                                if r["account"] == a
                            )
                            if (
                                incident["uid"] in payload
                                and payload[incident["uid"]]["utc"] == incident["utc"]
                            ):
                                key = incident["key"]
                        runner.publish(run, t, a, key, path)
                if t == 9:
                    shutil.copyfile(
                        work / "data/portal.sqlite", work / "out/backup.sqlite"
                    )
            if t == 10:
                write(work / "scratch/ledger.json", ledger(run, t))
                run_cmd(
                    work,
                    "python3 project/service.py history input/questions.json scratch/ledger.json out/inquiry.json",
                )
        freeze(work, run / "snapshots" / str(t))
        write(
            run / "receipts" / f"{t}.json",
            {a: receipts(run, a, CHANNELS) for a in CHANNELS},
        )
    write(
        run / "manifest.json",
        dict(
            protocol=VERSION,
            material_revision=MATERIAL_REVISION,
            scoring_revision=SCORING_REVISION,
            status="complete",
            image=IMAGE,
            turns=[{"turn": t} for t in range(1, 11)],
        ),
    )


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "reference"
    if mode not in (
        "reference",
        "noop",
        "latest-identity",
        "trust-stale-cache",
        "ignore-withdrawal",
        "fixed-ledger",
    ):
        raise ValueError(mode)
    with tempfile.TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as d:
        run = Path(d)
        drive(run, mode)
        print(json.dumps(grade(run), indent=2))


if __name__ == "__main__":
    main()
