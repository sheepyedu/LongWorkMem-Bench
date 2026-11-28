"""Control implementation used only in the reference checkout."""

import json
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from zoneinfo import ZoneInfo


def migrate(db):
    db.executescript(
        "create table if not exists series(code text primary key,anchor text,zone text,wall int);create table if not exists patch(ch text,uid text,utc text,primary key(ch,uid));"
    )
    for s in json.loads(Path("input/intake.json").read_text()):
        signed = (Path("input/records") / (s["order"] + ".txt")).read_text()
        db.execute(
            "insert or replace into series values(?,?,?,?)",
            (s["code"], s["anchor"], s["zone"], int("当地钟点" in signed)),
        )
    db.commit()


def events(db, start, end, ch):
    a = date.fromisoformat(start if len(start) == 10 else "1900-01-01")
    b = date.fromisoformat(end if len(end) == 10 else "2100-01-01")
    result = {
        u: dict(uid=u, utc=s, status="CONFIRMED")
        for u, s in db.execute("select uid,starts from events")
        if a <= date.fromisoformat(s[:10]) <= b
    }
    if not db.execute("select 1 from sqlite_master where name='series'").fetchone():
        return list(result.values())
    for code, anchor, zone, wall in db.execute("select * from series"):
        first = datetime.fromisoformat(anchor)
        if wall:
            first = first.astimezone(ZoneInfo(zone))
        current = first + timedelta(weeks=max(0, (a - first.date()).days // 7))
        while current.date() <= b:
            if current.date() >= a:
                uid = code + "-" + current.strftime("%Y%m%d")
                override = db.execute(
                    "select utc from patch where ch=? and uid=?", (ch, uid)
                ).fetchone()
                utc = (
                    override[0]
                    if override
                    else current.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                result[uid] = dict(uid=uid, utc=utc, status="CONFIRMED")
            current += timedelta(days=7)
    return list(result.values())
