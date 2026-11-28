"""Executed only during isolated replay. Weights and answers remain on the host."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def main():
    folder = Path(sys.argv[1])
    result = {}
    for check in json.loads((folder / "commands.json").read_bytes()):
        name, args, kind = check
        path = folder / (name + (".ics" if kind == "ics" else ".json"))
        if kind in ("ics", "file"):
            args = [*args, str(path)]
        try:
            if kind == "legacy":
                with sqlite3.connect("file:data/portal.sqlite?mode=ro", uri=True) as db:
                    row = db.execute(
                        "select uid from bookings where id=?", (args[0],)
                    ).fetchone()
                page = subprocess.run(
                    [
                        sys.executable,
                        "project/portal.py",
                        "request",
                        "/invite/" + args[1] + "?tz=UTC",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                result[name] = [
                    row[0] if row else None,
                    page.stdout if page.returncode == 0 else "",
                ]
                continue
            p = subprocess.run(
                [sys.executable, "project/service.py", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=8,
            )
            if p.returncode:
                result[name] = None
            elif kind == "stdout":
                result[name] = json.loads(p.stdout)
            elif kind == "ok":
                result[name] = True
            else:
                result[name] = path.is_file()
        except (sqlite3.Error, OSError, ValueError, subprocess.TimeoutExpired):
            result[name] = None
    (folder / "results.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main()
