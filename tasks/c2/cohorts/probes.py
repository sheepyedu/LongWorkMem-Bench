"""Prepare independent business inputs on frozen workspace copies."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from tasks.c1.runstate import freeze
from tasks.c2.grade import read
from tasks.c2.pilot import execute
from tasks.c2.scenario import write
from tasks.c2.subscriber import decode

from .oracle import events
from .oracle import rows as business_rows
from .scenario import ANNEX, CHANNELS, CUT, DAYS, registrations


def replay(run, t, image, mode):
    with tempfile.TemporaryDirectory(
        dir=os.getenv("C2_TEST_ROOT") or run.parent
    ) as root:
        work = Path(root) / "desk"
        snap = run / "snapshots" / str(t)
        freeze(snap, work)
        if mode in ("early", "late"):
            shutil.rmtree(work / "data")
            freeze(run / "snapshots/2/data", work / "data")
            path = work / "input/migration.json"
            m = json.loads(path.read_bytes())
            m["cutover"] = (
                "2026-01-01T00:00:00Z" if mode == "early" else "2026-03-01T00:00:00Z"
            )
            write(path, m)
        elif mode in ("annex", "signed"):
            shutil.rmtree(work / "data")
            (work / "data").mkdir()
            shutil.copyfile(
                work / "input/previous-release/out/backup.sqlite",
                work / "data/portal.sqlite",
            )
            path = work / "input" / ANNEX
            a = json.loads(path.read_bytes())
            if mode == "annex":
                a["utc_by_account"]["D"] = "11:35"
            write(path, a)
        elif mode == "restart":
            data = read(work, "out/backup.sqlite", bytes)
            if not data:
                return {}
            for name in ("input", "data", "notes", "out", "scratch"):
                shutil.rmtree(work / name)
                (work / name).mkdir()
            (work / "data/portal.sqlite").write_bytes(data)
        folder = Path(tempfile.mkdtemp(dir=work / "scratch")).relative_to(work)
        commands = []
        if mode in ("early", "late", "annex", "signed"):
            commands.extend((f"load{i}", ["import", "input"], "ok") for i in (1, 2))
        if mode in ("live", "early", "late", "annex", "signed", "restart"):
            for a in CHANNELS:
                for v in (
                    [6, 7]
                    if mode in ("annex", "signed")
                    else [3, 6, 7]
                    if mode == "restart"
                    else [t]
                ):
                    commands.append((f"view-{a}-{v}", ["view", a, str(v)], "stdout"))
        if t == 3 and mode == "live":
            from datetime import datetime

            for r in registrations():
                if datetime.fromisoformat(r["joined"]) < datetime.fromisoformat(CUT):
                    commands.append(
                        (
                            "legacy-" + r["account"],
                            [r["booking"], r["old_prefix"] + "-20260302"],
                            "legacy",
                        )
                    )
        if mode in ("restart", "incident"):
            for a in CHANNELS:
                desired = events(a, t)
                special = business_rows(a, t)["Q29", DAYS[1]]["uid"]
                for missing in (False, True):
                    rows = dict(desired)
                    if missing:
                        rows[special] = {**rows[special], "utc": "2026-03-09T19:27:00Z"}
                    file = folder / f"ledger-{a}-{missing}.json"
                    write(
                        work / file,
                        [dict(turn=7, receipt=a + "-00012", key="journal", rows=rows)],
                    )
                    commands.append(
                        (f"delta-{a}-{missing}", ["delta", a, str(t), str(file)], "ics")
                    )
        if mode == "history":
            questions = [
                dict(account=a, code="Q29", day=DAYS[1], asof=7) for a in CHANNELS
            ]
            write(work / folder / "q.json", questions)
            for changed in ("none", *CHANNELS):
                logs = {}
                for a in CHANNELS:
                    r = events(a, 7)
                    uid = business_rows(a, 7)["Q29", DAYS[1]]["uid"]
                    if changed == a:
                        r[uid] = {**r[uid], "utc": "2026-03-09T20:10:00Z"}
                    logs[a] = [dict(turn=6, receipt=a + "-00003", key="past", rows=r)]
                file = folder / (changed + ".json")
                write(work / file, logs)
                commands.append(
                    (changed, ["history", str(folder / "q.json"), str(file)], "file")
                )
        write(work / folder / "commands.json", commands)
        cmd = (
            f"python3 - {folder} <<'END_PROBE'\n"
            + Path(__file__).with_name("probe_io.py").read_text()
            + "\nEND_PROBE"
        )
        r = execute(work, cmd, image, timeout=240)
        if r["status"]:
            raise RuntimeError(f"offline driver failed: {r['output'][-300:]}")
        result = read(work, str(folder / "results.json"), json.loads)
        if not isinstance(result, dict):
            raise RuntimeError("missing replay evidence")
        for name, _, kind in commands:
            if result.get(name) is True and kind in ("ics", "file"):
                result[name] = read(
                    work,
                    str(folder / (name + (".ics" if kind == "ics" else ".json"))),
                    decode if kind == "ics" else json.loads,
                )
        if mode in ("early", "late", "annex", "signed") and not all(
            result.get("load" + str(i)) for i in (1, 2)
        ):
            return {}
        return result
