"""Verify and identify the common pre-amendment checkout before starting controls."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import tempfile

from . import sandbox, world
from .runstate import freeze


def fingerprint(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            value = ["link", os.readlink(path)]
        elif path.is_dir():
            value = ["dir"]
        else:
            value = ["file", path.stat().st_mode & 0o777, hashlib.sha256(path.read_bytes()).hexdigest()]
        digest.update(json.dumps([relative, value], ensure_ascii=False).encode() + b"\n")
    return digest.hexdigest()


def check_handoff(source, backend, parent):
    # Test the handoff on a throwaway copy. The unapproved batch begins with a
    # normal new ticket so that a partially committed prefix cannot pass.
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        work = Path(tmp) / "workspace"
        if freeze(source, work):
            raise ValueError("The handoff contains unsupported files")
        verify = """import hashlib,json,sqlite3
db=sqlite3.connect('file:data/tickets.sqlite?mode=ro',uri=True)
db.execute("pragma trusted_schema=off")
digest=hashlib.sha256(json.dumps(sorted(db.iterdump())).encode()).hexdigest()
print(json.dumps([digest, sorted(r[0] for r in db.execute('select shard from commits')),
                  sorted(r[0] for r in db.execute('select event_id from events'))]))"""
        def inspect():
            check = sandbox.shell(work, "python3 -I -S -c " + shlex.quote(verify), backend)
            if check["status"]:
                raise ValueError("Could not inspect the handoff database")
            return json.loads(check["output"])
        before = inspect()
        probe = [{"event_id": "transition-ordinary", "seq": 190, "source": "B", "ticket": "P-01",
                  "revision": 1, "dept": "ops", "status": "open"}, world._amendments()[0]]
        file = work / "input/transition.jsonl"
        file.write_text("".join(json.dumps(row) + "\n" for row in probe))
        command = "python3 project/tickets.py ingest data/tickets.sqlite input/transition.jsonl"
        response = sandbox.shell(work, command, backend)
        if response["status"] == 0 or inspect() != before:
            raise ValueError("Unopened approval interface accepted the batch or altered the live database")
        shards = sorted((work / "input/shards").glob("*.jsonl"))
        files = [work / "input/intake.jsonl", work / "input/late.jsonl", *shards]
        expected = {json.loads(line)["event_id"] for f in files for line in f.read_text().splitlines() if line.strip()}
        if not shards or before[1:] != [[p.name for p in shards], sorted(expected)]:
            raise ValueError("Handoff is missing earlier events or shard commits")
        file.write_text(json.dumps(probe[0]) + "\n")
        ordinary = sandbox.shell(work, command, backend)
        if ordinary["status"] or inspect()[2] != sorted(expected | {probe[0]["event_id"]}):
            raise ValueError("Handoff cannot process an ordinary new ticket")
    return {"sha256": fingerprint(source), "batch_exit": response["status"], "shards": len(shards), "events": len(expected)}
