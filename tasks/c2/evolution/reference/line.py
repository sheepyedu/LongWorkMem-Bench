"""Host reference implementation. Copied only into the control desk."""

from datetime import datetime, date, time, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo
from calendar_io import encode


def connect():
    db = sqlite3.connect(os.getenv("PORTAL_DB", "data/portal.sqlite"))
    db.row_factory = sqlite3.Row
    return db


def ingest(db, folder):
    db.executescript(
        "CREATE TABLE IF NOT EXISTS lines(code TEXT PRIMARY KEY,body TEXT); CREATE TABLE IF NOT EXISTS orders2(id TEXT PRIMARY KEY,v INTEGER,body TEXT); CREATE TABLE IF NOT EXISTS wire(code TEXT PRIMARY KEY,body TEXT);"
    )

    def put(table, items):
        for key, item in items:
            db.execute(
                "insert or replace into " + table + " values(?,?)",
                (key, json.dumps(item)),
            )

    if (folder / "portfolio.json").exists():
        put(
            "lines",
            [
                (s["code"], s)
                for s in json.loads((folder / "portfolio.json").read_text())
            ],
        )
    if (folder / "identities.json").exists():
        put("wire", json.loads((folder / "identities.json").read_text()).items())
    for f in (folder / "orders").glob("*.json"):
        b = json.loads(f.read_text())
        for r in b["rows"]:
            db.execute(
                "insert or ignore into orders2 values(?,?,?)",
                (r["id"], b["version"], json.dumps(r)),
            )
    db.commit()


def rows(db, c, lo, hi, v):
    terms = [
        json.loads(r["body"]) | {"version": r["v"]}
        for r in db.execute("select * from orders2 where v<=?", (v,))
    ]
    wires = {r["code"]: json.loads(r["body"]) for r in db.execute("select * from wire")}
    out = []
    start = max(date.fromisoformat(lo), date(2026, 3, 2))
    for entry in db.execute("select body from lines"):
        s = json.loads(entry[0])
        d = start + timedelta(days=(s["weekday"] - start.weekday()) % 7)
        while d <= date.fromisoformat(hi):
            today = d.isoformat()
            matches = [
                r
                for r in terms
                if c in r["channels"] and r["start"] <= today <= r["end"]
            ]
            excluded = {r["target"] for r in matches if "target" in r}
            ordered = sorted(
                (
                    r
                    for r in matches
                    if r.get("code") == s["code"] and r["id"] not in excluded
                ),
                key=lambda x: (x["rank"], x["version"], x["id"]),
            )
            p = ordered[-1] if ordered else s
            z = ZoneInfo(s["zone"] if p["basis"] == "wall" else "UTC")
            dt = datetime.combine(
                d + timedelta(days=p.get("shift_days", 0)),
                time.fromisoformat(p["clock"]),
                z,
            )
            prefix = wires.get(s["code"], {}).get(c, s["code"])
            out.append(
                dict(
                    code=s["code"],
                    day=today,
                    uid=f"{prefix}-{d:%Y%m%d}",
                    utc=dt.astimezone(timezone.utc).isoformat(),
                    status="CONFIRMED",
                )
            )
            d += timedelta(weeks=1)
    return out


def applied(log, v):
    state = {}
    for b in sorted(log, key=lambda b: (b["turn"], b["receipt"])):
        if b["turn"] <= v:
            state.update(b["rows"])
    return state


def output(name, val):
    Path(name).write_text(json.dumps(val))


def main():
    verb, *a = sys.argv[1:]
    with connect() as db:
        if verb == "import":
            ingest(db, Path(a[0]))
            return
        if verb in ("query", "feed", "delta"):
            channel, lo, hi, v, *paths = a
            data = rows(db, channel, lo, hi, int(v))
            if verb == "query":
                print(json.dumps(data))
                return
            if verb == "delta":
                prev = applied(json.loads(Path(paths[0]).read_text()), int(v))
                data = [
                    r
                    for r in data
                    if r["uid"] not in prev
                    or datetime.fromisoformat(prev[r["uid"]]["utc"])
                    != datetime.fromisoformat(r["utc"])
                    or prev[r["uid"]]["status"] != r["status"]
                ]
            Path(paths[-1]).write_text(encode(data))
            return
        questions = json.loads(Path(a[0]).read_text())
        ans = []
        logs = json.loads(Path(a[1]).read_text()) if verb == "history" else {}
        for q in questions:
            r = next(
                r
                for r in rows(db, q["channel"], q["day"], q["day"], q["asof"])
                if r["code"] == q["code"]
            )
            if verb == "history":
                got = (
                    applied(logs[q["channel"]], q["asof"]).get(r["uid"], {}).get("utc")
                )
                ans.append(
                    dict(
                        **q,
                        due=r["utc"],
                        received=got,
                        pending=got is None
                        or datetime.fromisoformat(got)
                        != datetime.fromisoformat(r["utc"]),
                    )
                )
            else:
                ans.append(
                    dict(
                        **q,
                        local=datetime.fromisoformat(r["utc"])
                        .astimezone(ZoneInfo("Europe/London"))
                        .strftime("%Y-%m-%d %H:%M"),
                    )
                )
        output(a[-1], ans)


if __name__ == "__main__":
    main()
