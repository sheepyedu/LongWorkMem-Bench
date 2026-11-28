"""I/O driver for frozen copies; expectations and weights stay on the host."""

import json
import os
from pathlib import Path
import subprocess
import sys
import socket
import sqlite3
import time
from urllib.request import urlopen
from urllib.parse import urlencode


def main():
    stage = int(sys.argv[1]) if sys.argv[1].isdigit() else sys.argv[1]
    d = str(Path(sys.argv[2]).parent) + "/"
    result = {}

    def line(*args):
        try:
            p = subprocess.run(
                [sys.executable, "project/line.py", *args],
                capture_output=True,
                timeout=15,
            )
            return p.stdout if p.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def obj(raw):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def output_probe(key, *args):
        path = Path(d + key + (".ics" if args[0] in ("feed", "delta") else ".json"))
        path.unlink(missing_ok=True)
        result[key] = line(*args, str(path)) is not None and path.is_file()

    if stage == "upgrade":

        def legacy_state(db):
            return [
                db.execute("select uid,starts from events order by uid").fetchall(),
                db.execute("select id,uid from bookings order by id").fetchall(),
            ]

        try:
            with sqlite3.connect("data/portal.sqlite") as db:
                db.execute(
                    "insert into bookings(id,uid) values(?,?)",
                    (Path(sys.argv[2]).parent.name + "-registration", "legacy-east"),
                )
                before = legacy_state(db)
            result["imported"] = all(
                line("import", "input") is not None for _ in range(2)
            )
            with sqlite3.connect("data/portal.sqlite") as db:
                after = legacy_state(db)
            for label, old, new in zip(("events", "bookings"), before, after):
                result[label] = (
                    len(set(old) & set(new)) / len(set(old) | set(new)) if old else 0
                )

        except sqlite3.Error:
            result["imported"] = False
        for ch in ("B", "C"):
            output_probe("feed" + ch, "feed", ch, "2026-03-16", "2026-03-16", "3")
    if stage == "cold":
        result["imported"] = all(
            line("import", d + "inbound") is not None for _ in range(2)
        )
        for version in (9, 10):
            for channel in ("A", "C"):
                output_probe(
                    f"feed{channel}{version}",
                    "feed",
                    channel,
                    "2026-03-16",
                    "2026-03-16",
                    str(version),
                )
    if stage == 2:
        result["base"] = obj(line("query", "B", "2026-03-02", "2026-03-23", "2"))
        result["load"] = all(
            line("import", d + "inbound") is not None for _ in range(2)
        )
        for v in ("2", "3", "4"):
            result["new" + v] = obj(line("query", "C", "2026-03-02", "2026-03-23", v))
    if stage in (3, 6, 9):
        for ch in "ABCD":
            lo, hi = (
                ("2026-10-19", "2026-11-09")
                if stage == 9
                else ("2026-03-02", "2026-03-23")
            )
            output_probe("feed" + ch, "feed", ch, lo, hi, str(stage))
    if stage == 5:
        output_probe("extra", "preview", d + "lookups.json")
    if stage == 8:
        for ch in "ABCD":
            for suffix in ("gap", "done"):
                output_probe(
                    ch + suffix,
                    "delta",
                    ch,
                    "2026-03-02",
                    "2026-03-23",
                    "8",
                    d + ch + suffix + "-receipts.json",
                )
    if stage == 10:
        output_probe("extra", "history", d + "lookups.json", d + "ledger.json")
    if stage in (1, 3, 9):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = subprocess.Popen(
            [sys.executable, "project/portal.py", "serve", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", port), 0.1):
                        break
                except OSError:
                    time.sleep(0.025)

            def get(url):
                try:
                    with urlopen(f"http://127.0.0.1:{port}" + url, timeout=4) as f:
                        return f.read(2000000).decode()
                except (OSError, ValueError):
                    return ""

            result["legacy"] = get("/invite/legacy-east?tz=Asia/Tokyo")
            if stage == 1:
                result["old"] = obj(
                    get("/api/events?channel=A&from=2026-03-05&to=2026-03-06")
                )
                for n in (0, 7, 2020, 2079):
                    result["p" + str(n)] = obj(
                        get(
                            "/api/pages?channel=A&from=2026-03-06&to=2046-02-09&limit=7&offset="
                            + str(n)
                        )
                    )
            else:
                for ch in "ABCD":
                    result["api" + ch] = obj(
                        get(
                            "/api/v2?"
                            + urlencode(
                                {
                                    "from": "2026-03-02",
                                    "to": "2026-03-23",
                                    "channel": ch,
                                    "asof": stage,
                                }
                            )
                        )
                    )
        finally:
            server.terminate()
            try:
                server.wait(timeout=1)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    Path(sys.argv[2]).write_text(json.dumps(result))


if __name__ == "__main__":
    main()
