"""Read the highest effective revision, including migrated revision zero."""
FIELDS = ("source", "ticket", "revision", "dept", "status")


def current(conn, through=None, arrived_by=None):
    effective = "SELECT source, ticket, revision, dept, status, -1 AS seq FROM baseline"
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
        effective += """ UNION ALL SELECT source, ticket, revision, dept, status, seq
            FROM events WHERE decision IN ('accepted', 'corrected')"""
    rows = conn.execute(f"""WITH timeline AS ({effective}), ranked AS (
        SELECT *, row_number() OVER (
            PARTITION BY source, ticket ORDER BY revision DESC, seq DESC) AS position
        FROM timeline WHERE (? IS NULL OR revision <= ?) AND (? IS NULL OR seq <= ?))
        SELECT source, ticket, revision, dept, status FROM ranked
        WHERE position=1 AND status <> 'withdrawn' ORDER BY source, ticket""", (through, through, arrived_by, arrived_by))
    return [dict(zip(FIELDS, row)) for row in rows]
