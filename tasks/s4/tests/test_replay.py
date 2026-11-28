"""Replay should require engine evidence even if archived text or scores are forged."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.s4.engine import connect
from tasks.s4.grade import read_lines, replay
from tasks.s4.league import GAMES, SCHEDULE
from tasks.s4.pilot import PROTOCOL
from tasks.s4.tools import Table


class TraceFormatTests(unittest.TestCase):
    def test_missing_and_scalar_journal_records_are_errors(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "journal.jsonl"
            for raw, expected in (("[", "Unreadable"), ("null", "Expected an object")):
                path.write_text('{"seq":1}\n' + raw + "\n")
                with self.assertRaisesRegex(ValueError, expected + ".*line 2"):
                    list(read_lines(path))


@unittest.skipUnless(
    os.environ.get("S4_TEST_DOCKER"), "Docker engine integration is opt-in"
)
class ReplayBoundaryTests(unittest.TestCase):
    def test_noop_and_forged_score(self):
        with TemporaryDirectory() as temp, connect() as engine:
            root = Path(temp)
            trace = root / "trace"
            trace.mkdir()
            table = Table(engine, trace / "mcp.jsonl", root / "memory.json")
            blocks, tables = [], {}
            session = "game-1"
            for index, name in enumerate(SCHEDULE, 1):
                if name in GAMES:
                    session = name
                init = table.open(name)
                table.set_goal(7 if name in GAMES else 1)
                table.dispatch("look", {})
                tables[name] = {"initial_position": init["position"], "stall": True}
                blocks.append(
                    {
                        "index": index,
                        "table": name,
                        "session": session,
                        "first_tool": table.seq,
                        "last_tool": table.seq,
                        "start_position": init["position"],
                        "end_position": init["position"],
                        "target": table.goal,
                        "segment_done": False,
                    }
                )
                (trace / f"{name}-events.json").write_text(
                    json.dumps(table.request("end_state"))
                )
            meta = {
                "protocol": PROTOCOL,
                "status": "complete",
                "schedule": SCHEDULE,
                "blocks": blocks,
                "tables": tables,
                "image": "longworkmem-catan:1",
            }
            (root / "manifest.json").write_text(json.dumps(meta))
            first = replay(root)
            self.assertEqual(first["score"], 0)
            self.assertEqual(sum(check["max"] for check in first["checks"]), 100)
            path = trace / "game-1-events.json"
            forged = json.loads(path.read_text())
            forged["winner"] = "You"
            path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, "terminal state differs"):
                replay(root)
