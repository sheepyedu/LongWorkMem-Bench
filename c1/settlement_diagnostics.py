"""Non-scoring probe for a second independently eligible recall of one transfer."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from . import settlement
from .grade_evidence import Probes, content
from .settlement_grade import ledger, matches


def add_second_recall(inp, plan):
    base = ledger(inp, plan)
    dispositions = dict(base["audit"])
    rows = [
        json.loads(line)
        for file in (inp / "packets").glob("*.jsonl")
        for line in file.read_text().splitlines()
    ]
    first = next(
        row
        for row in rows
        if row["kind"] == "recall" and dispositions.get(row["eid"]) == "posted"
    )
    new = dict(
        first,
        eid=first["eid"] + "-supplement",
        day=plan["day"],
        order=max(r["order"] for r in rows) + 1,
        seq=plan["lanes"][first["lane"]] + 1,
    )
    plan["lanes"][first["lane"]] = new["seq"]
    (inp / "packets/supplement.jsonl").write_text(json.dumps(new) + "\n")
    return new["eid"]


def diagnose(run, backend="docker"):
    run = Path(run).resolve()
    m = json.loads((run / "manifest.json").read_text())
    probes = Probes(backend, run)
    if not (run / "snapshots/6").is_dir():
        return {"available": False, "reason": "missing close"}
    with (
        tempfile.TemporaryDirectory(dir=run.parent) as tmp,
        probes.workspace(run / "snapshots/6") as work,
    ):
        host = Path(tmp)
        for t in range(1, 7):
            settlement.release(host, t, m["variant"], m["seed"], m["level"])
        inp = host / "input"
        plan = json.loads((inp / "jobs/close.json").read_text())
        eid = add_second_recall(inp, plan)
        expected = ledger(inp, plan)
        if dict(expected["audit"])[eid] != "duplicate":
            raise ValueError("Probe has no eligible duplicate")
        with tempfile.TemporaryDirectory(dir=work / "scratch") as td:
            desk = Path(td) / "input"
            shutil.copytree(inp, desk)
            if m.get("dispatch_window"):
                (desk / "handover.txt").unlink()
            (desk / "plan.json").write_text(json.dumps(plan))
            rel = desk.relative_to(work)
            dest = rel.parent / "result.json"
            err = probes.command(
                work, f"python3 project/settle.py {rel} {rel}/plan.json {dest}"
            )
            try:
                got = json.loads(content(work, dest))
            except (ValueError, OSError, RecursionError):
                got = None
            audit = got.get("audit") if isinstance(got, dict) else None
            decisions = (
                [
                    row[1]
                    for row in audit
                    if isinstance(row, list) and len(row) == 2 and row[0] == eid
                ]
                if isinstance(audit, list)
                else []
            )
            return {
                "available": not probes.infrastructure,
                "duplicate": not err and decisions == ["duplicate"],
                "entire_ledger": not err
                and all(matches(got, expected, f) for f in expected),
                "infrastructure": probes.infrastructure,
            }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    a = p.parse_args()
    print(json.dumps(diagnose(a.run), indent=2))
