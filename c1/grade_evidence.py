"""Bounded artifact reads and isolated executions on disposable frozen workspaces."""
from __future__ import annotations
import csv
import io
import json
import os
import re
import secrets
import shlex
import stat
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import sandbox
from .runstate import freeze
from .grade_oracle import DETAIL

MAX_BYTES = 16 * 1024 * 1024


def content(work, relative):
    path = work
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"{relative}: symbolic link")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_nlink != 1:
        raise ValueError(f"{relative}: expected a regular file of at most 16 MiB")
    return path.read_text(encoding="utf-8-sig")


def cell(value, name):
    if name in ("revision", "id", "number", "count"):
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"invalid {name}")
        return int(value)
    if not isinstance(value, str):
        raise ValueError(f"invalid {name}")
    return value


@dataclass
class Rows:
    values: list | None = None
    error: str = ""

    def project(self, func, where=lambda r: True):
        if self.error:
            return self
        return Rows([func(row) for row in self.values if where(row)])

    def match(self, expected, ordered=False):
        if self.error:
            return False, self.error
        expected = list(expected)
        actual, want = Counter(self.values), Counter(expected)
        if actual != want:
            missing = list((want - actual).items())[:2]
            extra = list((actual - want).items())[:2]
            return False, f"{len(self.values)} rows; missing {missing!r}, extra {extra!r}"
        if ordered and self.values != expected:
            return False, "row order differs from the published order"
        return True, f"{len(self.values)} rows matched"

    @classmethod
    def read(cls, work, name, fields, fmt, legacy_format=False):
        try:
            raw = content(work, name)
            if fmt == "text":
                return cls(raw.splitlines())
            if fmt == "csv":
                reader = csv.DictReader(io.StringIO(raw, newline=""))
                headers = reader.fieldnames or []
                if len(set(headers)) != len(headers) or not set(fields) <= set(headers):
                    raise ValueError(f"required columns {fields}, found {headers}")
                if legacy_format and headers != list(fields):
                    raise ValueError(f"legacy header differs: {headers}")
                rows = reader
            else:
                rows = json.loads(raw)
                if not isinstance(rows, list):
                    raise ValueError("expected a JSON array")
            result = []
            for row in rows:
                if legacy_format and row["number"] != str(int(row["number"])):
                    raise ValueError(f"legacy number is not normalized: {row['number']!r}")
                result.append(tuple(cell(row[f], f) for f in fields))
            return cls(result)
        except (KeyError, ValueError, TypeError, OSError, csv.Error) as exc:
            return cls(error=f"{name}: {str(exc)[:240]}")


# SQLite may need to roll back a hot journal after R6. Open the disposable copy
# inside the candidate sandbox. A broken/missing table cannot mask a valid one.
INSPECT = """
import json, sqlite3, sys
from pathlib import Path
if not Path(sys.argv[1]).is_file():
    sys.exit("database missing")
db = sqlite3.connect(sys.argv[1])
db.execute('PRAGMA trusted_schema=OFF')
db.execute('PRAGMA query_only=ON')
result = {}
for name, cols in [('events','event_id,decision'), ('commits','shard')]:
    try:
        rows = db.execute(f'SELECT {cols} FROM {name} LIMIT 10001').fetchall()
        if len(rows) > 10000 or not all(isinstance(v, str) for row in rows for v in row):
            raise ValueError('invalid or oversized audit table')
        result[name] = rows
    except (sqlite3.Error, ValueError) as exc:
        result[name] = str(exc)
Path(sys.argv[2]).write_text(json.dumps(result))
"""
TICKETS = "python3 project/tickets.py"


class Probes:
    def __init__(self, backend, run):
        self.backend = backend
        self.infrastructure = []
        self.verified = {}
        self.temp_root = os.getenv("C1_TEST_ROOT") or (Path(run).resolve().parent if backend == "docker" else None)

        self.image = None
        self.image_error = ""
        manifest = Path(run) / "manifest.json"
        if backend == "docker":
            self.image = os.getenv("C1_IMAGE") or sandbox.IMAGE
            if manifest.exists():
                try:
                    recorded = json.loads(content(Path(run), "manifest.json")).get("image")
                    if recorded is not None:
                        if not isinstance(recorded, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", recorded):
                            raise ValueError("invalid recorded Docker image digest")
                        self.image = recorded
                except (ValueError, TypeError, OSError, AttributeError) as exc:
                    self.image_error = f"cannot determine recorded sandbox image: {exc}"

    def execute(self, work, command, timeout):
        if self.image_error:
            raise RuntimeError(self.image_error)
        options = {"image": self.image} if self.backend == "docker" else {}
        return sandbox.shell(work, command, backend=self.backend, timeout=timeout, **options)

    def check_mount(self, work):
        # The sandbox must read a fresh host nonce and write it back to the same
        # workspace. An empty Docker bind mount can otherwise resemble a broken CLI.
        nonce = secrets.token_hex(16)
        with tempfile.NamedTemporaryFile(dir=work / "input", delete=False) as f:
            marker = Path(f.name)
            f.write(nonce.encode())
        receipt = self.output_path(work)
        try:
            code = ("import sqlite3,sys; from pathlib import Path; "
                    "sqlite3.connect(':memory:').execute('SELECT 1').fetchone(); "
                    "Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes())")
            command = f"python3 -I -S -c {shlex.quote(code)} {marker.relative_to(work)} {receipt}"
            result = self.execute(work, command, 30)
            if result["status"] != 0 or content(work, receipt) != nonce:
                detail = str(result.get("output", ""))[-220:].rstrip()
                raise RuntimeError(f"workspace read/write verification failed (exit {result['status']}): {detail}")
        finally:
            marker.unlink(missing_ok=True)
            (work / receipt).unlink(missing_ok=True)

    def command(self, work, command):
        try:
            if work not in self.verified:
                self.check_mount(work)
                self.verified[work] = ""
            if self.verified[work]:
                return self.verified[work]
            result = self.execute(work, command, 60)
        except (RuntimeError, OSError, ValueError) as exc:
            message = f"sandbox unavailable: {str(exc)[:300]}"
            self.verified[work] = message
            if message not in self.infrastructure:
                self.infrastructure.append(message)
            return message
        if result["status"] != 0:
            return f"command exited {result['status']}: {result.get('output', '')[-240:]}"
        return ""

    @contextmanager
    def workspace(self, source):
        with tempfile.TemporaryDirectory(prefix="c1-check-", dir=self.temp_root) as tmp:
            work = Path(tmp) / "work"
            if source.is_dir() and not source.is_symlink():
                freeze(source, work)
            else:
                work.mkdir()
            for folder in ("scratch", "out", "data", "notes", "project", "input"):
                path = work / folder
                if path.is_symlink() or (path.exists() and not path.is_dir()):
                    path.unlink()
                path.mkdir(exist_ok=True)
            yield work

    def audit(self, work, db="data/tickets.sqlite"):
        path = self.output_path(work)
        error = self.command(work, f"python3 -I -S -c {shlex.quote(INSPECT)} {shlex.quote(db)} {path}")
        try:
            if error:
                raise ValueError(error)
            report = json.loads(content(work, path))
            def table(name):
                rows = report[name]
                if not isinstance(rows, list):
                    return Rows(error=f"{name}: {rows}")
                return Rows([tuple(row) for row in rows])
            return table("events"), table("commits")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            failure = Rows(error=f"audit: {str(exc)[:240]}")
            return failure, failure

    @staticmethod
    def output_path(work):
        scratch = work / "scratch"
        if scratch.is_symlink() or not scratch.is_dir():
            raise ValueError("invalid workspace scratch directory")
        with tempfile.NamedTemporaryFile(dir=scratch, delete=False) as target:
            return str(Path(target.name).relative_to(work))

    def query(self, work, through=None, db="data/tickets.sqlite"):
        path = self.output_path(work)
        opt = "" if through is None else f" --through {through}"
        command = f"{TICKETS} query {db}{opt} > {path}"
        error = self.command(work, command)
        return Rows(error=error) if error else Rows.read(work, path, DETAIL, "json")
