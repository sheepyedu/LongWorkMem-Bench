"""Host-owned subscriber and append-only business receipts, separate from the worktree."""

from datetime import datetime, timezone
from pathlib import Path
import json
import re
from icalendar import Calendar
from tasks.w1.runstate import safe_file
from .scenario import write


def instant(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamp requires UTC offset")
    return (
        dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def decode(data):
    try:
        cal = Calendar.from_ical(data)
        if cal.name != "VCALENDAR" or cal.get("VERSION") != "2.0":
            raise ValueError("expected VCALENDAR 2.0")
        result = {}
        for event in cal.walk("VEVENT"):
            uid = str(event["UID"]).strip()
            start = event.decoded("DTSTART")
            if not uid or uid in result or not isinstance(start, datetime):
                raise ValueError("invalid or duplicate occurrence")
            status = str(event.get("STATUS", "CONFIRMED")).upper()
            if status not in ("CONFIRMED", "CANCELLED", "TENTATIVE"):
                raise ValueError("invalid STATUS")
            result[uid] = dict(uid=uid, utc=instant(start.isoformat()), status=status)
        return result
    except Exception as exc:
        raise ValueError("invalid calendar: " + type(exc).__name__) from exc


def receipts(run, ch):
    if ch not in ("A", "B"):
        raise ValueError("unknown channel")
    file = run / "subscriber" / (ch + ".json")
    return json.loads(file.read_text()) if file.exists() else []


def accept(run, t, ch, key, rows):
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", key):
        raise ValueError("invalid key")
    log = receipts(run, ch)
    for batch in log:
        if batch["key"] == key:
            if batch["rows"] != rows:
                raise ValueError("key conflict")
            return dict(receipt=batch["receipt"], already_received=True)
    if not rows:
        raise ValueError("empty release")
    receipt = f"{ch}-{len(log) + 1:05}"
    log.append(dict(turn=t, key=key, receipt=receipt, rows=rows))
    write(run / "subscriber" / (ch + ".tmp"), log)
    (run / "subscriber" / (ch + ".tmp")).replace(run / "subscriber" / (ch + ".json"))
    return dict(receipt=receipt, already_received=False)


def publish(run, t, channel, key, file):
    rel = Path(file)
    if rel.is_absolute() or rel.parts[:1] != ("out",) or ".." in rel.parts:
        raise ValueError("expected out/ file")
    work = run / "work"
    safe_file(work / "out", work / rel)
    return accept(run, t, channel, key, decode((work / rel).read_bytes()))


def interrupt(run):
    # A transport interruption between commit and ACK; B fails before commit.
    order = {}
    for ch in ("A", "B"):
        uid = "M42-20260327"
        row = dict(uid=uid, utc="2026-03-27T16:30:00Z", status="CONFIRMED")
        order[ch] = dict(key="urgent-0327-" + ch, **row)
        if ch == "A":
            accept(run, 7, ch, order[ch]["key"], {uid: row})
    write(run / "work/input/incident.json", order)
