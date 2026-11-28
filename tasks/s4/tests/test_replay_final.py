import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.s4.engine import IMAGE
from tasks.s4.records import write
from tasks.s4.runtime import environment, replay, state_receipt
from tasks.s4.schedule import FILING_SHIFTS, PHASES, PROMPTS, PROTOCOL


def witness(root, image):
    actions = json.loads(Path(__file__).with_name("witness.json").read_text())
    trace = root / "trace"
    trace.mkdir(parents=True)
    index = 0
    blocks = []
    with environment(image, trace, root / "notes") as desk:
        for i, phase in enumerate(PHASES, 1):
            desk.start(phase)
            first = desk.seq + 1
            before = state_receipt(desk)
            (trace / f"prompt-{i}.txt").write_text(PROMPTS[phase])
            skip = (
                phase.endswith("_opening")
                and desk.active.state["phase"] == "PLAY_TURN"
                and not any(
                    k == "ROLL" for _, k, _ in desk.active.request("legal")["actions"]
                )
            )
            while not skip and not desk.closed and not desk.active.done():
                args = actions[index]
                index += 1
                got = desk.dispatch(
                    "act", dict(args, position=desk.active.state["position"])
                )
                if "error" in got:
                    raise AssertionError((phase, index, args, got["error"]))
            if phase in {f"shift_{n}" for n in FILING_SHIFTS}:
                state = desk.active.state
                desk.dispatch(
                    "notes",
                    {
                        "op": "write",
                        "name": phase,
                        "text": json.dumps(
                            {"position": state["position"], "hand": state["hand"]}
                        ),
                    },
                )
            blocks.append(
                {
                    "index": i,
                    "phase": phase,
                    "table": "A",
                    "first_tool": first,
                    "last_tool": desk.seq,
                    "before": before,
                    "after": state_receipt(desk),
                }
            )
    assert index == len(actions)
    write(
        root / "manifest.json",
        {
            "protocol": PROTOCOL,
            "status": "complete",
            "case": "site21",
            "arm": "single",
            "opponent": "strategic",
            "image": image,
            "blocks": blocks,
        },
    )
    return replay(root), blocks


@unittest.skipUnless(os.getenv("S4_TEST_DOCKER"), "Docker opt-in")
class EarlyLeagueTests(unittest.TestCase):
    def test_perfect_reference_and_incomplete_replay(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            score, blocks = witness(root, IMAGE)
            self.assertEqual(
                (len(blocks), score["score"], score["authorization"]["correct"]),
                (40, 100, 2),
            )
            self.assertEqual(
                (blocks[12]["phase"], blocks[31]["phase"], blocks[39]["phase"]),
                ("amendment", "clearing", "commission"),
            )
            self.assertTrue(all(score["filings"].values()))
            meta = json.loads((root / "manifest.json").read_text())
            meta["blocks"].pop()
            write(root / "manifest.json", meta)
            with self.assertRaises(ValueError):
                replay(root)

    def test_player_surface_only_exposes_board_operations(self):
        import subprocess
        import sys

        from tasks.s4.tools import broker

        with TemporaryDirectory() as tmp:
            loc = Path(tmp)
            with (
                environment(IMAGE, loc, loc / "notes") as desk,
                broker(desk) as (addr, token),
            ):
                desk.start(PHASES[0])
                calls = [
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "look", "arguments": {"board": True}},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "end_state", "arguments": {}},
                    },
                ]
                proc = subprocess.run(
                    [sys.executable, "-m", "tasks.s4.tools", addr, token],
                    input="".join(json.dumps(r) + "\n" for r in calls),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                tools, board, hidden = map(json.loads, proc.stdout.splitlines())
                self.assertEqual(
                    {t["name"] for t in tools["result"]["tools"]},
                    {"look", "act", "notes"},
                )
                view = json.loads(board["result"]["content"][0]["text"])
                self.assertEqual(view["state"]["position"], 22)
                self.assertEqual(len(view["state"]["tiles"]), 19)
                self.assertIn(
                    "error", json.loads(hidden["result"]["content"][0]["text"])
                )
                self.assertNotIn("score", view)

    def test_archived_games_and_tampering(self):
        import tarfile

        from tasks.s4.codex_audit import audit

        catalogue = Path(__file__).resolve().parents[3] / "rollout/s4"
        for name in ("deepseek-flash-claude", "gpt61terra-codex"):
            source = catalogue / name
            with self.subTest(model=name), TemporaryDirectory() as tmp:
                root = Path(tmp)
                with tarfile.open(source / "replay.tar.xz") as package:
                    package.extractall(root, filter="data")
                expected = json.loads((source / "grade.json").read_text())
                self.assertEqual(replay(root, IMAGE), expected)
                if name == "gpt61terra-codex":
                    report = audit(root)
                    self.assertEqual(
                        report["usage"],
                        json.loads((source / "usage.json").read_text())["usage"],
                    )
                else:
                    from tasks.s4.audit import inspect

                    report = inspect(root)["summary"]
                    usage = json.loads((source / "usage.json").read_text())
                    self.assertFalse(report["faults"])
                    self.assertEqual(report["usage"], usage["usage"])
                    self.assertEqual(report["requests"], usage["requests"])
                    self.assertEqual(report["compact_events"], usage["compact_events"])
                path = root / "trace/mcp.jsonl"
                rows = path.read_text().splitlines()
                first = json.loads(rows[0])
                first["result"]["desk"] = "B"
                rows[0] = json.dumps(first)
                path.write_text("\n".join(rows) + "\n")
                with self.assertRaisesRegex(ValueError, "replay mismatch"):
                    replay(root, IMAGE)
