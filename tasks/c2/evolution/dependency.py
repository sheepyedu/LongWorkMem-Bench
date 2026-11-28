"""Unweighted same-program paired diagnostic on frozen code, without model calls."""

import argparse
import json
import os
from pathlib import Path
import tempfile

from tasks.c1.runstate import freeze
from tasks.c2.grade import read
from tasks.c2.pilot import execute
from tasks.c2.scenario import write
from tasks.c2.subscriber import instant
from .scenario import VERSION, DAYS, identities


def compare(run, image=None):
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("protocol") != VERSION or manifest["status"] != "complete":
        raise ValueError("requires a complete evolution run")
    # Same source, date, inquiry and entitlements; only B's historical receipt changes.
    question = dict(channel="B", code="Q29", day=DAYS[2], asof=7)
    uid = identities()["Q29"]["B"] + "-" + DAYS[2].replace("-", "")
    cases = []
    for stamp in ("2026-03-16T16:30:00Z", "2026-03-16T17:00:00Z"):
        with tempfile.TemporaryDirectory(
            dir=os.getenv("C2_TEST_ROOT") or run.parent
        ) as root:
            work = Path(root) / "work"
            freeze(run / "snapshots/10", work)
            case = Path(tempfile.mkdtemp(dir=work / "scratch")).relative_to(work)
            write(work / case / "question.json", [question])
            log = {c: [] for c in "ABCD"}
            log["B"] = [
                dict(
                    turn=6,
                    receipt="B-00001",
                    key="paired",
                    rows={uid: dict(uid=uid, utc=stamp, status="CONFIRMED")},
                )
            ]
            write(work / case / "ledger.json", log)
            result = execute(
                work,
                f"python3 project/line.py history {case}/question.json {case}/ledger.json {case}/answer.json",
                image or manifest["image"],
            )
            answer = read(work, str(case / "answer.json"), json.loads)
            expected_due = "2026-03-16T16:30:00Z"
            ok = False
            if (
                isinstance(answer, list)
                and len(answer) == 1
                and isinstance(answer[0], dict)
            ):
                row = answer[0]
                try:
                    ok = (
                        result["status"] == 0
                        and all(row.get(k) == v for k, v in question.items())
                        and instant(row["due"]) == expected_due
                        and instant(row["received"]) == stamp
                        and row["pending"] is (expected_due != stamp)
                    )
                except (KeyError, TypeError, ValueError):
                    pass
            cases.append(
                dict(
                    received=stamp,
                    expected_due=expected_due,
                    answer=answer,
                    exit=result["status"],
                    passed=ok,
                )
            )
    return dict(
        turn=10,
        diagnostic="change only the historical receipt",
        cases=cases,
        passed=all(c["passed"] for c in cases),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--image")
    args = parser.parse_args()
    print(json.dumps(compare(args.run.resolve(), args.image), indent=2))
