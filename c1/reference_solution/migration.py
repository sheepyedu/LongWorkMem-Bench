"""Link original import rows to the unambiguous entries in the identity registry."""
import csv
from collections import defaultdict


def write_rows(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def migrate(conn, mapping, quarantine):
    tickets = defaultdict(set)
    with mapping.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            tickets[int(row["number"])].add(row["ticket"])
    conn.execute("""CREATE TABLE IF NOT EXISTS baseline(
        source TEXT, ticket TEXT, revision INTEGER, dept TEXT, status TEXT,
        PRIMARY KEY(source,ticket))""")
    rejected = []
    fields = ("id", "number", "dept", "status")
    for record in conn.execute("SELECT id, number, dept, status FROM legacy ORDER BY id"):
        identifier, number, dept, status = record
        matches = tickets[number]
        if len(matches) != 1:
            rejected.append(dict(zip(fields, record)))
            continue
        conn.execute("INSERT OR REPLACE INTO baseline VALUES ('A', ?, 0, ?, ?)",
                     (next(iter(matches)), dept, status))
    write_rows(quarantine, fields, rejected)
