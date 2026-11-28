import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.s4.continuation import environment, replay, state_receipt
from tasks.s4.early_league import FILING_SHIFTS, episode
from tasks.s4.pilot import write


def witness(root, image, length):
    ep = episode(length)
    actions = json.loads(Path(__file__).with_name("early-witness.json").read_text())[
        str(length)
    ]
    trace = root / "trace"
    trace.mkdir(parents=True)
    index = 0
    blocks = []
    with environment(
        image,
        trace,
        root / "notes",
        "single",
        "strategic",
        ep.rules,
        ep.shared_turns,
        ep.board,
    ) as desk:
        for i, phase in enumerate(ep.phases, 1):
            desk.start(phase)
            first = desk.seq + 1
            before = state_receipt(desk)
            (trace / f"prompt-{i}.txt").write_text(ep.prompt(phase, "single", "site21"))
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
            "protocol": ep.protocol,
            "status": "complete",
            "case": "site21",
            "arm": "single",
            "opponent": "strategic",
            "image": image,
            "blocks": blocks,
        },
    )
    return replay(root, episode=ep), blocks


@unittest.skipUnless(os.getenv("S4_TEST_DOCKER"), "Docker opt-in")
class EarlyLeagueTests(unittest.TestCase):
    def test_both_deadlines_reachable_and_truncation_rejected(self):
        image = os.getenv("S4_EARLY_TEST_IMAGE", "longworkmem-catan:1")
        with TemporaryDirectory() as tmp:
            initial = []
            for length in (32, 40):
                root = Path(tmp) / str(length)
                result, blocks = witness(root, image, length)
                initial.append(blocks[0]["before"])
                self.assertEqual(len(blocks), length)
                self.assertEqual(blocks[-9]["phase"], "clearing")
                self.assertEqual(result["authorization"]["correct"], 2)
                self.assertIsNone(result["terminal"])
                self.assertTrue(all(result["filings"].values()))
                m = json.loads((root / "manifest.json").read_text())
                m["blocks"] = m["blocks"][:-1]
                write(root / "manifest.json", m)
                with self.assertRaises(ValueError):
                    replay(root, episode=episode(length))
            self.assertEqual(*initial)
