"""Fixed-position witnesses for continuation and its paired intervention."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.s4.continuation import (
    ARMS,
    CASES,
    FEEDER,
    PHASES,
    PROTOCOL,
    SPURS,
    environment,
    evaluate,
    replay,
    state_receipt,
    user_prompt,
)
from tasks.s4.pilot import write


def play(desk, kind, value=None):
    choice = next(
        (
            i
            for i, k, v in desk.active.request("legal")["actions"]
            if k == kind and (value is None or value == v)
        ),
        None,
    )
    if choice is None:
        raise AssertionError((kind, value, desk.active.request("legal")))
    return desk.dispatch(
        "act", {"position": desk.active.state["position"], "choice": choice}
    )


def offer(desk, give):
    return desk.dispatch(
        "act",
        {"position": desk.active.state["position"], "give": give, "take": {"BRICK": 1}},
    )


@unittest.skipUnless(os.environ.get("S4_TEST_DOCKER"), "Docker opt-in")
class ContinuationTest(unittest.TestCase):
    image = os.getenv("S4_CONTINUATION_TEST_IMAGE", "longworkmem-catan:1")

    def case(self, dest, arm, case, opponent):
        trace = dest / "trace"
        trace.mkdir(parents=True)
        edge, node = SPURS[CASES[case]]
        phases = []
        with environment(self.image, trace, dest / "notes", arm, opponent) as desk:
            for i, phase in enumerate(PHASES, 1):
                desk.start(phase)
                before, first = state_receipt(desk), desk.seq + 1
                (trace / f"prompt-{i}.txt").write_text(user_prompt(phase, arm, case))
                if phase == "prepare":
                    view = desk.dispatch("look", {"board": True})
                    self.assertIn("adjacency", view["state"])
                    self.assertIn(21, view["state"]["adjacency"]["16"])
                    self.assertTrue(play(desk, "BUILD_ROAD", FEEDER)["segment_done"])
                elif phase == "revision":
                    result = desk.dispatch(
                        "act", {"position": desk.active.state["position"], "choice": 1}
                    )
                    self.assertIn("read-only", result["error"])
                elif phase == "interlude" and arm == "switch":
                    self.assertEqual(desk.label, "B")
                    offer(desk, {"SHEEP": 1, "WHEAT": 1})
                    play(desk, "CONFIRM_TRADE", "Ash")
                    play(desk, "BUILD_ROAD")
                    play(desk, "END_TURN")
                elif phase == "route":
                    self.assertEqual(desk.label, "A")
                    self.assertTrue(play(desk, "BUILD_ROAD", edge)["segment_done"])
                elif phase == "delivery":
                    self.assertNotIn("BRICK", desk.active.state["hand"])
                    looked = desk.dispatch("look", {})
                    self.assertNotIn(
                        node,
                        [
                            v
                            for _, k, v in looked["legal"]["actions"]
                            if k == "BUILD_SETTLEMENT"
                        ],
                    )
                    accepts = offer(desk, {"SHEEP": 1, "WHEAT": 1})
                    partners = {
                        v
                        for _, k, v in accepts["legal"]["actions"]
                        if k == "CONFIRM_TRADE"
                    }
                    self.assertEqual(
                        partners, {"Sail", "Ash"} if opponent == "base" else {"Sail"}
                    )
                    play(desk, "CONFIRM_TRADE", "Sail")
                    final = play(desk, "BUILD_SETTLEMENT", node)
                    self.assertEqual(final["state"]["hand"]["WHEAT"], 2)
                after = state_receipt(desk)
                phases.append(
                    {
                        "index": i,
                        "phase": phase,
                        "table": desk.label,
                        "before": before,
                        "after": after,
                        "first_tool": first,
                        "last_tool": desk.seq,
                    }
                )
                if phase in {"interlude", "revision"}:
                    self.assertEqual(before["main"], after["main"])
        meta = {
            "protocol": PROTOCOL,
            "status": "complete",
            "arm": arm,
            "case": case,
            "opponent": opponent,
            "blocks": phases,
            "image": self.image,
        }
        write(dest / "manifest.json", meta)
        result = replay(dest)
        self.assertEqual(result["score"], result["max"])
        self.assertEqual(result["side_delivery"], arm == "switch")
        return phases

    def test_pair_shares_paused_board_and_history_flips_correct_spur(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            phases = [
                self.case(root / f"{arm}-{case}", arm, case, "cautious")
                for case in CASES
                for arm in ARMS
            ]
            hashes = {rows[3]["before"]["main"] for rows in phases}
            self.assertEqual(len(hashes), 1)
            first = root / "single-keep"
            lines = (first / "trace/mcp.jsonl").read_text().splitlines()
            row = json.loads(lines[-1])
            row["result"]["state"]["hand"]["WHEAT"] = 999
            lines[-1] = json.dumps(row)
            (first / "trace/mcp.jsonl").write_text("\n".join(lines) + "\n")
            with self.assertRaisesRegex(ValueError, "Transcript replay mismatch"):
                replay(first)

    def test_opponent_trade_control(self):
        with TemporaryDirectory() as d:
            self.case(Path(d) / "base", "single", "keep", "base")


class ContinuationScoringTest(unittest.TestCase):
    def test_no_action_zero_and_wrong_route_is_not_credited(self):
        self.assertEqual(evaluate("keep", [])["score"], 0)
        result = evaluate(
            "revise",
            [
                {
                    "table": "A",
                    "phase": "route",
                    "tool": "act",
                    "result": {
                        "event": {"action": "BUILD_ROAD", "value": [6, 23]},
                        "state": {"hand": {"WHEAT": 1}},
                    },
                },
                {
                    "table": "B",
                    "phase": "interlude",
                    "tool": "act",
                    "result": {
                        "event": {"action": "BUILD_SETTLEMENT", "value": 52, "seq": 90},
                        "state": {"hand": {"WHEAT": 3}},
                    },
                },
            ],
        )
        self.assertEqual(result["score"], 0)
