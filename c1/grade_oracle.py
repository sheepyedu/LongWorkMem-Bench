"""Private C1 expectations derived only from the released source fixtures."""
import copy
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing


DETAIL = ("source", "ticket", "revision", "dept", "status")
LEGACY = ("number", "dept", "status")
QUARANTINE = ("id", *LEGACY)
TARGET = ("A", "0017")
APPROVAL = "OPS-42"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Ledger:
    def __init__(self, inputs, variant):
        self.variant = variant
        mapping = defaultdict(set)
        for row in read_csv(inputs / "mapping.csv"):
            mapping[int(row["number"])].add(row["ticket"])
        self.revisions = defaultdict(dict)
        self.quarantine = []
        self.legacy = []
        self.decisions = {}
        self.incoming = {}
        self.shards = []
        with closing(sqlite3.connect(inputs / "initial.sqlite")) as db:
            for row_id, number, dept, status in db.execute("SELECT id,number,dept,status FROM legacy ORDER BY id"):
                self.legacy.append((row_id, number, dept, status))
                tickets = mapping[number]
                if len(tickets) == 1:
                    key = ("A", next(iter(tickets)))
                    self.revisions[key][0] = (dept, status)
                else:
                    self.quarantine.append((row_id, number, dept, status))

    def ingest(self, path):
        for row in sorted(records(path), key=lambda r: r["seq"]):
            eid = row["event_id"]
            if eid in self.decisions:
                continue
            self.incoming[eid] = row
            key = (row["source"], row["ticket"])
            rev = row["revision"]
            prior = self.revisions[key].get(rev)
            value = row["dept"], row["status"]
            if prior is None:
                decision = "accepted"
            elif prior == value:
                decision = "unchanged"
            elif (self.variant == "B" and key == TARGET and rev == 3 and
                  row.get("approval") == APPROVAL and prior[1] == value[1]):
                decision = "corrected"
            else:
                decision = "conflict"
            self.decisions[eid] = decision
            if decision in ("accepted", "corrected"):
                self.revisions[key][rev] = value

    def detail(self, through=None):
        rows = []
        for key, versions in sorted(self.revisions.items()):
            available = [rev for rev in versions if through is None or rev <= through]
            if not available:
                continue
            rev = max(available)
            dept, status = versions[rev]
            if status != "withdrawn":
                rows.append((*key, rev, dept, status))
        return rows

    def all_versions(self):
        return [(*key, rev, *value) for key, versions in self.revisions.items() for rev, value in versions.items()]

    def summary(self):
        return sorted(Counter(r[3] for r in self.detail()).items())


def timeline(inputs, variant):
    ledger = Ledger(inputs, variant)
    states = {2: copy.deepcopy(ledger)}
    for turn, filename in [(3, "intake.jsonl"), (4, "late.jsonl")]:
        ledger.ingest(inputs / filename)
        states[turn] = copy.deepcopy(ledger)
    for i, path in enumerate(sorted((inputs / "shards").glob("*.jsonl")), 1):
        ledger.ingest(path)
        ledger.shards.append(path.name)
        if i == 16:
            states[6] = copy.deepcopy(ledger)
    states[8] = copy.deepcopy(ledger)
    for turn, filename in [(9, "amendments.jsonl"), (10, "withdrawals.jsonl")]:
        ledger.ingest(inputs / filename)
        states[turn] = copy.deepcopy(ledger)
    return states
