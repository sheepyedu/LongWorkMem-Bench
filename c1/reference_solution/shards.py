"""Commit the receipt ledger and shard completion marker together."""
from intake import ingest


def apply(conn, path):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS commits(shard TEXT PRIMARY KEY)")
        if not conn.execute("SELECT 1 FROM commits WHERE shard=?", (path.name,)).fetchone():
            ingest(conn, path)
            conn.execute("INSERT INTO commits(shard) VALUES (?)", (path.name,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
