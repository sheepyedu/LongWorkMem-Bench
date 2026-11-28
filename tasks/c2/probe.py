"""Read-only acceptance client on a disposable application checkout."""

import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request


def main():
    stage = int(sys.argv[1])
    out = {"errors": {}}

    def call(name, *args):
        if args and args[-1].endswith(".ics"):
            Path(args[-1]).unlink(missing_ok=True)
        try:
            return (
                subprocess.run(
                    [sys.executable, "project/" + name, *args],
                    capture_output=True,
                    timeout=7,
                ).returncode
                == 0
            )
        except subprocess.TimeoutExpired:
            return False

    def bookings():
        try:
            with sqlite3.connect("data/portal.sqlite") as db:
                return sorted(db.execute("select id,uid from bookings").fetchall())
        except sqlite3.Error:
            return []

    booked = [
        ("seat-" + k, k)
        for k in sorted(("legacy-east", "legacy-west", "M42-20260306", "K17-20260306"))
    ]
    if stage == 2:
        out["stable"] = (
            call("portal.py", "migrate")
            and call("portal.py", "migrate")
            and bookings() == booked
        )
    out["bookings"] = bookings() == booked
    if stage in (4, 5, 6):
        for ch in ("A", "B"):
            out["feed" + ch] = call(
                "prepare.py",
                ch,
                "2026-03-06",
                "2026-03-27",
                "scratch/feed" + ch + ".ics",
            )
    if stage == 7:
        for name in ("missing", "done"):
            out[name] = call(
                "recover.py",
                "scratch/job.json",
                "scratch/" + name + ".json",
                "B",
                "scratch/" + name + ".ics",
            )
    if stage == 8:
        out["export"] = call(
            "prepare.py", "A", "2026-04-01", "2026-06-30", "scratch/export.ics"
        )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "project/portal.py", "serve", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for i in range(80):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.025)
        for key, path in {
            "list": "/?tz=Asia/Tokyo&from=2026-03-05&to=2026-03-06",
            "detail": "/invite/legacy-west?tz=America/New_York",
            "api": "/api/events?channel=B&from=2026-03-01&to=2026-03-31",
        }.items():
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}" + path, timeout=2
                ) as r:
                    txt = r.read(200000).decode()
                out[key] = json.loads(txt) if key == "api" else txt[:8000]
            except (OSError, ValueError) as exc:
                out["errors"][key] = type(exc).__name__
    finally:
        proc.terminate()
        proc.wait()
    print(json.dumps(out))


if __name__ == "__main__":
    main()
