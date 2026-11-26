"""Ticket service command line, including the original CSV commands."""
import argparse
import json
import runpy
import sqlite3
import sys
from pathlib import Path

from migration import migrate


def apply_shard(conn, path):
    from shards import apply
    apply(conn, path)


def main():
    command, *arguments = sys.argv[1:]
    if command in {"import-csv", "export-csv"}:
        runpy.run_path(str(Path(__file__).with_name("legacy.py")), run_name="__main__")
        return
    if command == "replay":
        from replay import rebuild
        rebuild(*map(Path, arguments))
        return

    filename, *arguments = arguments
    with sqlite3.connect(filename) as conn:
        if command == "migrate":
            migrate(conn, *map(Path, arguments))
        elif command == "ingest":
            from intake import ingest
            ingest(conn, Path(arguments[0]))
        elif command == "query":
            from views import current
            parser = argparse.ArgumentParser()
            parser.add_argument("--through", type=int)
            cutoff = parser.parse_args(arguments).through
            print(json.dumps(current(conn, cutoff), ensure_ascii=False))
        elif command == "report":
            from reports import report
            report(conn, *map(Path, arguments))
        else:
            raise SystemExit(f"Unknown command {command}")


if __name__ == "__main__":
    main()
