"""Host reference; installed as project/service.py only in calibration sandboxes."""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from calendar_io import encode


def ingest(db, folder):
    db.execute(
        "create table if not exists cohort_data(name text primary key, value text)"
    )

    def save(name, data):
        db.execute(
            "insert into cohort_data values(?,?) on conflict(name) do update set value=excluded.value",
            (name, json.dumps(data)),
        )

    catalog = json.loads((folder / "schedule.json").read_text())
    save("schedule", catalog)
    save("roster", json.loads((folder / "roster.json").read_text()))
    for rule in catalog["classes"].values():
        if rule["basis"] == "signed-annex":
            annex = json.loads((folder / rule["ref"]).read_text())
            if annex["status"] != "signed" or annex["id"] != rule["approval"]:
                raise ValueError("invalid annex")
            save(rule["ref"], annex)
    if (folder / "migration.json").exists():
        save("migration", json.loads((folder / "migration.json").read_text()))
    for file in (folder / "orders").glob("*.json"):
        batch = json.loads(file.read_text())
        for order in batch["rows"]:
            save("order/" + order["id"], dict(order, version=batch["version"]))


def view(config, account, version):
    catalog = config["schedule"]
    orders = [
        v
        for k, v in config.items()
        if k.startswith("order/")
        and v["version"] <= version
        and account in v["accounts"]
    ]
    out = []
    for reg in config["roster"]:
        if reg["account"] != account:
            continue
        code = reg["code"]
        rule = catalog["classes"][code]
        prefix = reg["old_prefix"]
        migration = config.get("migration")
        if (
            migration
            and version >= migration["version"]
            and datetime.fromisoformat(reg["joined"])
            >= datetime.fromisoformat(migration["cutover"])
        ):
            prefix = migration["prefixes"][reg["channel"]][code]
        for day in catalog["days"]:
            daily = [o for o in orders if o["day"] == day]
            revoked = {o["target"] for o in daily if "target" in o}
            allowed = sorted(
                (o for o in daily if o.get("code") == code and o["id"] not in revoked),
                key=lambda o: (o["version"], o["id"]),
            )
            if allowed:
                clock = allowed[-1]["utc_clock"]
                zone = timezone.utc
            elif rule["basis"] == "signed-annex":
                clock = config[rule["ref"]]["utc_by_account"][account]
                zone = timezone.utc
            else:
                clock = rule["clock"]
                zone = ZoneInfo(rule["zone"])
            utc = (
                datetime.fromisoformat(day + "T" + clock)
                .replace(tzinfo=zone)
                .astimezone(timezone.utc)
                .isoformat()
            )
            out.append(
                dict(
                    account=account,
                    code=code,
                    day=day,
                    booking=reg["booking"],
                    uid=prefix + "-" + day.replace("-", ""),
                    utc=utc,
                )
            )
    return out


def applied(batches, v):
    state = {}
    for b in sorted(batches, key=lambda b: (b["turn"], b["receipt"])):
        if b["turn"] <= v:
            state.update(b["rows"])
    return state


def same(a, b):
    return (
        a is not None
        and b is not None
        and datetime.fromisoformat(a) == datetime.fromisoformat(b)
    )


def main():
    verb, *args = sys.argv[1:]
    with sqlite3.connect(os.getenv("PORTAL_DB", "data/portal.sqlite")) as db:
        if verb == "import":
            ingest(db, Path(args[0]))
            return
        config = {
            k: json.loads(v)
            for k, v in db.execute("select name,value from cohort_data")
        }
    if verb == "history":
        qfile, logs, dest = map(Path, args)
        by_account = json.loads(logs.read_text())
        answers = []
        for q in json.loads(qfile.read_text()):
            a, v = q["account"], q["asof"]
            row = next(
                r
                for r in view(config, a, v)
                if r["day"] == q["day"] and r["code"] == q["code"]
            )
            got = applied(by_account[a], v).get(row["uid"], {}).get("utc")
            answers.append(
                dict(
                    **q,
                    uid=row["uid"],
                    due=row["utc"],
                    received=got,
                    pending=not same(got, row["utc"]),
                )
            )
        dest.write_text(json.dumps(answers))
        return
    a, v, *rest = args
    rows = view(config, a, int(v))
    if verb == "view":
        print(json.dumps(rows))
        return
    if verb != "delta":
        raise ValueError(verb)
    log, dest = map(Path, rest)
    old = applied(json.loads(log.read_text()), int(v))
    delta = []
    for row in rows:
        prev = old.get(row["uid"], {})
        if not same(prev.get("utc"), row["utc"]) or prev.get("status") != "CONFIRMED":
            delta.append(dict(row, status="CONFIRMED"))
    dest.write_text(encode(delta))


if __name__ == "__main__":
    main()
