"""An independent implementation of the read side, folding snapshots in Python."""
from collections import defaultdict

FIELDS = ("source", "ticket", "revision", "dept", "status")


def current(conn, through=None, arrived_by=None):
    versions = defaultdict(dict)
    for source, ticket, rev, dept, status in conn.execute("SELECT * FROM baseline"):
        versions[source, ticket][rev] = (dept, status)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "events" in tables:
        for source, ticket, rev, dept, status in conn.execute("""SELECT source,ticket,revision,dept,status
                FROM events WHERE decision IN ('accepted','corrected') AND (? IS NULL OR seq <= ?)
                ORDER BY seq""", (arrived_by, arrived_by)):
            versions[source, ticket][rev] = (dept, status)
    result = []
    for (source, ticket), history in sorted(versions.items()):
        allowed = [rev for rev in history if through is None or rev <= through]
        if allowed:
            rev = max(allowed)
            dept, status = history[rev]
            if status != "withdrawn":
                result.append({"ticket": ticket, "dept": dept, "status": status,
                               "source": source, "revision": rev})
    return result
