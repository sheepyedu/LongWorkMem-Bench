"""Compatibility encoder for subscribers using one VEVENT per stable occurrence UID."""
from datetime import datetime, timezone


def encode(rows):
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Schedule Desk//EN"]
    for row in rows:
        stamp = datetime.fromisoformat(row["utc"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines.extend(["BEGIN:VEVENT","UID:"+row["uid"],"DTSTAMP:20260101T000000Z",
                      "DTSTART:"+stamp,"STATUS:"+row["status"],"END:VEVENT"])
    return "\r\n".join(lines+["END:VCALENDAR",""])
