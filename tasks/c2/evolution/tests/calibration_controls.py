"""Reproduce the no-op, reference and single-fault C2 controls without an LLM."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from ..case_grade import grade
from .test_evolution import control


def main():
    totals = {}

    def score(name, run):
        result = grade(run)
        totals[name] = [result["legacy_total"], result["total"]]

    with TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as tmp:
        run = Path(tmp)
        control(run, noop=True)
        score("no-op", run)
    with TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as tmp:
        run = Path(tmp)
        control(run)
        score("reference", run)
        for turn, name, change in [
            (
                3,
                "rewrite-bookings",
                "if sys.argv[1]=='import':\n    with connect() as db: db.execute('delete from bookings')",
            ),
            (9, "read-only-restore", "if sys.argv[1]=='import': sys.exit(0)"),
            (
                10,
                "fixed-ledger",
                "if sys.argv[1]=='history': sys.argv[3]='scratch/history.json'",
            ),
        ]:
            entry = run / "snapshots" / str(turn) / "project/line.py"
            original = entry.read_text()
            marker = 'if __name__ == "__main__":\n'
            if original.count(marker) != 1:
                raise ValueError("reference entrypoint changed")
            code = (
                marker + "\n".join("    " + line for line in change.splitlines()) + "\n"
            )
            entry.write_text(original.replace(marker, code))
            try:
                score(name, run)
            finally:
                entry.write_text(original)
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
