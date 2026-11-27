"""Standalone reference using the participant's archived notices and handover."""

import csv
import json
from collections import defaultdict
from pathlib import Path
import sys


def settle(project, input_dir):
    calendar = {}
    for file in sorted(project.glob("notice-*.csv")):
        with file.open() as lines:
            for row in csv.DictReader(lines):
                # The new contract replaces all dates from its start, including
                # dates after expiry. Earlier scopes have no fallback.
                for day in range(int(row["start"]), 10):
                    key = day, row["desk"], row["band"]
                    calendar[key] = row if day <= int(row["end"]) else None
    signer = (project / "authority.txt").read_text().strip()
    schedule = defaultdict(list)
    seen = set()
    for line in (input_dir / "guarantees.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["id"] not in seen:
            schedule[r["day"]].append(r)
            seen.add(r["id"])
    amounts = {}
    history, bookings = [], []
    result = {k: [] for k in ("decisions", "posted", "balance")}
    for day in range(1, 10):
        for r in sorted(schedule[day], key=lambda row: row["seq"]):
            key = r["desk"], r["band"]
            term = calendar.get((day, *key))
            if term is None:
                disposition = "expired"
            elif r["channel"] != term["channel"]:
                disposition = "channel"
            elif r["signer"] != signer:
                disposition = "signature"
            elif amounts.get(key, 0) + r["amount"] > int(term["limit"]):
                disposition = "capacity"
            else:
                disposition = "posted"
                amounts[key] = amounts.get(key, 0) + r["amount"]
                bookings.append([*key, r["id"], r["amount"]])
            history.append([r["id"], disposition])
        if day in (3, 6, 9):
            result["decisions"].extend([day, *row] for row in history)
            result["posted"].extend([day, *row] for row in bookings)
            result["balance"].extend([day, *key, v] for key, v in amounts.items())
    return result


if __name__ == "__main__":
    source, dest = map(Path, sys.argv[1:])
    dest.write_text(json.dumps(settle(Path(__file__).parent, source)))
