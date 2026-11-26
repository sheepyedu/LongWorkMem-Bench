import csv
import json
import shlex
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from c1 import world
from c1.runstate import freeze


class C1WorldTests(unittest.TestCase):
    def test_progressive_release_and_one_decision_line(self):
        first_turn = {"mapping.csv": 2, "event-format.txt": 3, "decision.txt": 3, "intake.jsonl": 3,
                      "late.jsonl": 4, "batch.py": 5, "sample/trial.jsonl": 5, "shards/017.jsonl": 6,
                      "worker.log": 7, "amendments.jsonl": 9, "withdrawals.jsonl": 10}
        with TemporaryDirectory() as tmp:
            homes = [Path(tmp) / variant for variant in ("A", "B")]
            for turn in range(1, 13):
                prompts = [world.release(home, turn, home.name) for home in homes]
                self.assertEqual(prompts[0], prompts[1])
                contents = [{p.relative_to(h): p.read_bytes() for p in h.rglob("*") if p.is_file()}
                            for h in homes]
                self.assertEqual(contents[0].keys(), contents[1].keys())
                differences = [p for p in contents[0] if contents[0][p] != contents[1][p]]
                self.assertEqual(differences, [Path("input/decision.txt")] if turn >= 3 else [])
                for name, due in first_turn.items():
                    self.assertEqual(Path("input", name) in contents[0], turn >= due)
                if turn == 3:
                    a, b = [files[Path("input/decision.txt")].decode().splitlines() for files in contents]
                    self.assertEqual(a[:-1], b[:-1])
                    self.assertEqual([a[-1], b[-1]], list(world.POLICIES.values()))
            inputs = homes[0] / "input"
            self.assertEqual(20, len(list((inputs / "shards").glob("*.jsonl"))))
            for name in ("intake.jsonl", "late.jsonl"):
                self.assertFalse(any("approval" in json.loads(row) for row in (inputs / name).read_text().splitlines()))
            amendments = [json.loads(row) for row in (inputs / "amendments.jsonl").read_text().splitlines()]
            registered = [row for row in amendments if (row["source"], row["ticket"], row["revision"],
                          row.get("approval"), row["status"]) == ("A", "0017", 3, "OPS-42", "closed")]
            self.assertEqual([row["event_id"] for row in registered], ["change-201"])
            after_close = [json.loads(row) for row in (inputs / "withdrawals.jsonl").read_text().splitlines()]
            self.assertTrue(any(row["seq"] > 205 and row["revision"] <= 3 and row["status"] != "withdrawn"
                                for row in after_close))

    def test_original_cli_and_restart_preserve_data(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            world.initialize(work)
            old = (work / "input/initial.sqlite").read_bytes()
            self.assertEqual(old, (work / "data/tickets.sqlite").read_bytes())
            for command, path in (("import-csv", "input/legacy.csv"), ("export-csv", "scratch/out.csv")):
                subprocess.run([sys.executable, "project/tickets.py", command, "scratch/test.sqlite", path],
                               cwd=work, check=True)
            with (work / "scratch/out.csv").open(newline="") as stream:
                self.assertEqual(list(csv.reader(stream)), [
                    ["number", "dept", "status"], ["7", "维修,一线", "open"],
                    ["93", "North", "pending"], ["7", "North", "closed"]])
            (work / "project/tickets.py").write_text("# customer edit")
            with closing(sqlite3.connect(work / "data/tickets.sqlite")) as db, db:
                db.execute("DELETE FROM legacy WHERE id=1")
            world.release(work, 1, "A")
            self.assertEqual((work / "project/tickets.py").read_text(), "# customer edit")
            self.assertNotEqual((work / "data/tickets.sqlite").read_bytes(), old)
            self.assertEqual((work / "input/initial.sqlite").read_bytes(), old)

    def test_real_sqlite_interrupt_and_recovery(self):
        # Exercise the controller with a small compatible writer, independent of the C1 reference solution.
        writer = '''
import json

def apply_shard(conn, path):
    if conn.execute("SELECT 1 FROM commits WHERE shard=?", (path.name,)).fetchone():
        return
    with conn:
        for line in path.read_text().splitlines():
            eid = json.loads(line)["event_id"]
            conn.execute("INSERT INTO events VALUES (?, 'accepted')", (eid,))
            # OPTIONAL_EARLY_COMMIT
        conn.execute("INSERT INTO commits VALUES (?)", (path.name,))
'''
        for premature in (False, True):
            with self.subTest(premature=premature), TemporaryDirectory() as tmp:
                work = Path(tmp) / "work"
                for turn in range(1, 7):
                    world.release(work, turn, "B")
                source = writer.replace("# OPTIONAL_EARLY_COMMIT", "conn.commit()") if premature else writer
                (work / "project/tickets.py").write_text(source)
                with closing(sqlite3.connect(work / "data/tickets.sqlite")) as db, db:
                    db.execute("CREATE TABLE events (event_id TEXT PRIMARY KEY,decision TEXT)")
                    db.execute("CREATE TABLE commits (shard TEXT PRIMARY KEY)")
                cmd = shlex.split(world.batch_command(True))
                job = subprocess.run([sys.executable, *cmd[1:]], cwd=work, capture_output=True, text=True)
                self.assertEqual(job.returncode, 86, job.stderr)
                self.assertEqual(json.loads(job.stdout), {"event": "precommit_interrupt", "shard": "017.jsonl",
                                 "visible": ["s17-01", "s17-02"], "in_transaction": True})
                snap = Path(tmp) / "stopped"
                freeze(work, snap)
                with closing(sqlite3.connect(snap / "data/tickets.sqlite")) as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM commits").fetchone()[0], 16)
                    self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 65 if premature else 64)
                    self.assertEqual(db.execute("SELECT event_id FROM events WHERE event_id LIKE 's17-%'").fetchall(),
                                     [("s17-01",)] if premature else [])
                if not premature:
                    cmd = shlex.split(world.batch_command())
                    for _ in range(2):
                        subprocess.run([sys.executable, *cmd[1:]], cwd=work, capture_output=True, check=True)
                    with closing(sqlite3.connect(work / "data/tickets.sqlite")) as db:
                        self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 80)
                        self.assertEqual(db.execute("SELECT count(*) FROM commits").fetchone()[0], 20)
