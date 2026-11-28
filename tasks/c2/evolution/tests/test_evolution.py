import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from tasks.c1.runstate import freeze
from tasks.c2.pilot import execute
from tasks.c2.scenario import write
from tasks.c2.starter.calendar_io import encode
from tasks.c2.subscriber import receipts, decode
from tasks.c2.evolution import runner
from tasks.c2.evolution.grade import grade
from tasks.c2.evolution.scenario import CHANNELS, VERSION, DAYS, LATE, setup
from tasks.c2.evolution.receiver import publish

IMAGE = "longworkmem-calendar:1"


def run_cmd(work, cmd):
    r = execute(work, cmd, IMAGE)
    if r["status"]:
        raise RuntimeError(r["output"])
    return r["output"]


def control(run, noop=False):
    work = run / "work"
    setup(work)
    manifest = dict(status="complete", protocol=VERSION, image=IMAGE, turns=[])
    for t in range(1, 11):
        runner.release(run, t)
        if not noop:
            portal = work / "project/portal.py"
            if t == 1:
                s = portal.read_text().replace(
                    "while len(out) < limit:",
                    "while end is not None or len(out)<limit:",
                )
                start = s.index('    if parts.path == "/api/events":')
                s = (
                    s[:start]
                    + """    if parts.path == "/api/pages":
        offset, limit = int(query["offset"]),int(query["limit"])
        page=rows[offset:offset+limit]
        return "application/json",json.dumps(dict(items=page,next=offset+limit if offset+limit<len(rows) else None))
"""
                    + s[start:]
                )
                portal.write_text(s)
            if t == 2:
                shutil.copy(
                    Path(__file__).resolve().parents[1] / "reference/line.py",
                    work / "project/line.py",
                )
            if t in (2, 3, 6, 7, 9):
                run_cmd(work, "python3 project/line.py import input")
            if t == 3:
                s = portal.read_text()
                pos = s.index('    if parts.path == "/api/pages":')
                s = (
                    s[:pos]
                    + """    if parts.path == "/api/v2":
        import line
        with line.connect() as other:
            return "application/json",json.dumps(line.rows(other,query["channel"],start,end,int(query["asof"])))
"""
                    + s[pos:]
                )
                portal.write_text(s)
            if t == 5:
                run_cmd(
                    work,
                    "python3 project/line.py preview input/support.json out/preview.json",
                )
            if t in (4, 6, 7, 8, 9):
                dates = LATE if t == 9 else DAYS
                for c in CHANNELS:
                    logs = receipts(run, c, CHANNELS)
                    write(work / "scratch/log.json", logs)
                    path = f"out/plan-{c}.ics" if t == 7 else "out/dispatch.ics"
                    run_cmd(
                        work,
                        f"python3 project/line.py delta {c} {dates[0]} {dates[-1]} {t} scratch/log.json {path}",
                    )
                    rows = decode((work / path).read_bytes())
                    if t == 7:
                        continue
                    if t == 8 and c == "D":
                        incident = json.loads(
                            (work / "input/interruption.json").read_text()
                        )[1]
                        special = rows.pop(incident["row"]["uid"])
                        (work / "out/pending.ics").write_text(encode([special]))
                        publish(run, t, c, incident["key"], "out/pending.ics")
                    if rows:
                        (work / path).write_text(encode(rows.values()))
                        publish(run, t, c, f"batch-{t}-{c}", path)
            if t == 9:
                shutil.copy(work / "data/portal.sqlite", work / "out/backup.sqlite")
                run_cmd(
                    work,
                    f"python3 project/line.py feed C {LATE[0]} {LATE[-1]} 9 out/new-C.ics",
                )
            if t == 10:
                write(
                    work / "scratch/history.json",
                    {c: receipts(run, c, CHANNELS) for c in CHANNELS},
                )
                run_cmd(
                    work,
                    "python3 project/line.py history input/questions.json scratch/history.json out/inquiry.json",
                )
        freeze(work, run / "snapshots" / str(t))
        write(
            run / "receipts" / f"{t}.json",
            {c: receipts(run, c, CHANNELS) for c in CHANNELS},
        )
        manifest["turns"].append(dict(turn=t))
    write(run / "manifest.json", manifest)


@unittest.skipUnless(os.getenv("C2_TEST_ROOT"), "Docker shared path required")
class Evolution(unittest.TestCase):
    def test_native_tool_boundary(self):
        with TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as d:
            run = Path(d)
            setup(run / "work")
            (run / "trace").mkdir()
            (run / "work/out/one.ics").write_text(
                encode(
                    [dict(uid="item", utc="2026-03-02T15:00:00Z", status="CONFIRMED")]
                )
            )
            calls = [
                (
                    "shell",
                    dict(
                        command='test ! -e ../manifest.json && test ! -e /var/run/docker.sock && test -z "$ARK_API_KEY" && ! touch input/change 2>/dev/null && echo yes > notes/write && cat notes/write'
                    ),
                ),
                ("publish", dict(channel="D", key="receipt", file="out/one.ics")),
                ("receipts", dict(channel="D")),
                ("receipts", dict(channel="A")),
                ("publish", dict(channel="D", key="receipt", file="out/one.ics")),
            ]
            queries = [dict(id=0, method="tools/list")] + [
                dict(id=i, method="tools/call", params=dict(name=n, arguments=a))
                for i, (n, a) in enumerate(calls, 1)
            ]
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tasks.c2.evolution.runner",
                    "--serve",
                    d,
                    "4",
                    IMAGE,
                ],
                input="".join(json.dumps(v) + "\n" for v in queries),
                text=True,
                capture_output=True,
                check=True,
            )
            results = [json.loads(l)["result"] for l in r.stdout.splitlines()]
            schemas = {
                s["name"]: set(s["inputSchema"]["required"])
                for s in results[0]["tools"]
            }
            for (n, a), o in zip(calls, results[1:]):
                self.assertEqual(set(a), schemas[n])
                self.assertFalse(o.get("isError"))
            vals = [json.loads(o["content"][0]["text"]) for o in results[1:]]
            self.assertEqual(vals[0]["output"].strip(), "yes")
            self.assertEqual(vals[2][0]["key"], "receipt")
            self.assertEqual(vals[3], [])
            self.assertTrue(vals[4]["already_received"])

    def test_reference_and_mutants(self):
        with TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as d:
            run = Path(d)
            control(run)
            g = grade(run)
            self.assertEqual(
                100,
                g["total"],
                [(k, v) for k, v in g["checks"].items() if v["fraction"] != 1],
            )
            snap = run / "snapshots"
            (snap / "7/out/plan-B.ics").write_text("not ICS")
            (snap / "10/out/inquiry.json").write_text("[]")
            logs = json.loads((run / "receipts/8.json").read_text())
            logs["C"].append(dict(logs["C"][-1], key="redundant", receipt="C-99999"))
            write(run / "receipts/8.json", logs)
            bad = grade(run)["checks"]
            for k in ("rollback.plan.B", "history.file.due", "resume.side-effects.C"):
                self.assertEqual(bad[k]["earned"], 0, k)
            self.assertEqual(bad["resume.state.C"]["fraction"], 1)
