"""Rebuild using only the release archive and the production import paths."""
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from intake import ingest
from migration import migrate
from shards import apply


def rebuild(inputs, destination, quarantine):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / "working.sqlite"
        with closing(sqlite3.connect(staged)) as conn:
            with closing(sqlite3.connect(inputs / "initial.sqlite")) as initial:
                initial.backup(conn)
            with conn:
                migrate(conn, inputs / "mapping.csv", quarantine)
                ingest(conn, inputs / "intake.jsonl")
                ingest(conn, inputs / "late.jsonl")
            for path in sorted((inputs / "shards").glob("*.jsonl")):
                apply(conn, path)
            with conn:
                ingest(conn, inputs / "amendments.jsonl")
                ingest(conn, inputs / "withdrawals.jsonl")
        os.replace(staged, destination)
