"""Keep receipt decisions separate from the effective value of each revision."""
import json

from decision import authorized


def initialize_events(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS events(
        event_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, source TEXT NOT NULL,
        ticket TEXT NOT NULL, revision INTEGER NOT NULL, dept TEXT NOT NULL,
        status TEXT NOT NULL, approval TEXT, decision TEXT NOT NULL)""")


def classify(conn, key):
    base = conn.execute("""SELECT dept, status FROM baseline
        WHERE source=? AND ticket=? AND revision=?""", key).fetchone()
    effective = tuple(base) if base else None
    arrivals = conn.execute("""SELECT event_id, dept, status, approval, decision
        FROM events WHERE source=? AND ticket=? AND revision=? ORDER BY seq""", key)
    for event_id, dept, status, approval, previous in arrivals.fetchall():
        payload = (dept, status)
        if effective is None:
            decision = "accepted"
        elif effective == payload:
            decision = "unchanged"
        elif authorized(key, effective, payload, approval):
            decision = "corrected"
        else:
            decision = "conflict"
        if decision in {"accepted", "corrected"}:
            effective = payload
        if decision != previous:
            conn.execute("UPDATE events SET decision=? WHERE event_id=?", (decision, event_id))


def ingest(conn, path):
    initialize_events(conn)
    with path.open(encoding="utf-8-sig") as stream:
        arrivals = sorted((json.loads(line) for line in stream if line.strip()),
                          key=lambda row: row["seq"])
    for row in arrivals:
        key = (row["source"], row["ticket"], row["revision"])
        inserted = conn.execute("""INSERT INTO events
            (event_id, seq, source, ticket, revision, dept, status, approval, decision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unchanged') ON CONFLICT(event_id) DO NOTHING""",
            (row["event_id"], row["seq"], *key, row["dept"], row["status"], row.get("approval")))
        if inserted.rowcount:
            classify(conn, key)
