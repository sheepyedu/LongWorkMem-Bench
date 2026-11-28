"""Unscored paired test of the frozen R2 program, with the very same new series."""

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from tasks.c1.runstate import freeze
from .grade import api
from .pilot import execute
from .scenario import SERIES, write


def paired(run):
    manifest = json.loads((run / "manifest.json").read_text())
    result = {}
    for swapped in (False, True):
        with TemporaryDirectory(dir=os.getenv("C2_TEST_ROOT") or run.parent) as temp:
            work = Path(temp) / "desk"
            freeze(run / "snapshots/2", work)
            rows = [dict(item, code=code) for item, code in zip(SERIES, ("N54", "J67"))]
            if swapped:
                rows[0]["order"], rows[1]["order"] = rows[1]["order"], rows[0]["order"]
            write(work / "input/intake.json", rows)
            cmd = "python3 project/portal.py migrate >/dev/null && python3 project/http_read.py '/api/events?from=2026-03-06&to=2026-03-13&channel=A'"
            reply = execute(work, cmd, manifest["image"])
            try:
                values = (
                    api(json.loads(reply["output"])) if reply["status"] == 0 else {}
                )
            except ValueError:
                values = {}
            result["swapped" if swapped else "original"] = {
                k: v["utc"] for k, v in values.items()
            }
    a, b = result.values()
    keys = sorted(set(a) | set(b))
    changed = [k for k in keys if a.get(k) != b.get(k)]
    expected = ["J67-20260313", "N54-20260313"]
    result["pass"] = (
        changed == expected
        and all(
            a.get(prefix + "-20260306")
            == b.get(prefix + "-20260306")
            == "2026-03-06T15:00:00Z"
            for prefix in ("N54", "J67")
        )
        and all(
            a.get(k) == v and b.get(k) == w
            for k, v, w in [
                (expected[0], "2026-03-13T15:00:00Z", "2026-03-13T14:00:00Z"),
                (expected[1], "2026-03-13T14:00:00Z", "2026-03-13T15:00:00Z"),
            ]
        )
    )
    result["changed_uids"] = changed
    return result


if __name__ == "__main__":
    print(json.dumps(paired(Path(sys.argv[1]).resolve()), indent=2))
