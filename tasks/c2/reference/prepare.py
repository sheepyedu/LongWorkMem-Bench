import sys, os, sqlite3
from pathlib import Path
from calendar_io import encode
from service import events

ch, start, end, target = sys.argv[1:]
with sqlite3.connect(os.getenv("PORTAL_DB", "data/portal.sqlite")) as db:
    codes = [code + "-" for (code,) in db.execute("select code from series")]
    Path(target).write_text(
        encode(
            [
                r
                for r in events(db, start, end, ch)
                if any(r["uid"].startswith(c) for c in codes)
            ]
        )
    )
