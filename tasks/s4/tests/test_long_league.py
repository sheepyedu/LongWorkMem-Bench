"""Validate long-horizon work orders against a real, deterministic game."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.s4.continuation import FEEDER, SPURS, environment, replay, state_receipt
from tasks.s4.long_league import CASES, EPISODE, evaluate
from tasks.s4.pilot import write

from .test_continuation import offer, play


def operate(desk, until_city=None):
    while not desk.active.done() and not desk.closed:
        options = desk.active.request("legal")["actions"]
        hand = desk.active.state["hand"]
        city = next(
            (v for _, k, v in options if k == "BUILD_CITY" and v == until_city), None
        )
        if city is not None and hand.get("WHEAT", 0) >= 4:
            play(desk, "BUILD_CITY", city)
            continue
        bank = [
            v
            for _, k, v in options
            if k == "MARITIME_TRADE" and v[-1] == "ORE" and v[0] != "WHEAT"
        ]
        if bank and hand.get("ORE", 0) < 3:
            play(
                desk,
                "MARITIME_TRADE",
                min(bank, key=lambda v: sum(x is not None for x in v[:-1])),
            )
        elif any(k == "END_TURN" for _, k, _ in options):
            play(desk, "END_TURN")
        elif any(k == "REJECT_TRADE" for _, k, _ in options):
            play(desk, "REJECT_TRADE")
        elif options:
            _, kind, value = options[0]
            if kind == "DISCARD_RESOURCE":
                choices = [
                    v for _, k, v in options if k == kind and v not in ("WHEAT", "ORE")
                ]
                if choices:
                    value = max(choices, key=lambda v: hand.get(v, 0))
            play(desk, kind, value)
        else:
            raise AssertionError("Non-terminal board did not offer any pending action")


def witness(root, image, case, opponent, *, wrong_city=False, episode=EPISODE):
    route, target = CASES[case]
    edge, node = SPURS[route]
    trace = root / "trace"
    trace.mkdir(parents=True)
    blocks = []
    saw_sail_offer = False
    with environment(
        image,
        trace,
        root / "notes",
        "single",
        opponent,
        episode.rules,
        episode.shared_turns,
    ) as desk:
        for index, phase in enumerate(episode.phases, 1):
            desk.start(phase)
            before = state_receipt(desk)
            first = desk.seq + 1
            (trace / f"prompt-{index}.txt").write_text(
                episode.prompt(phase, "single", case)
            )
            if phase == "mobilize":
                play(desk, "BUILD_ROAD", FEEDER)
            elif phase == "quote":
                result = offer(desk, {"SHEEP": 1, "WHEAT": 1})
                saw_sail_offer = any(
                    k == "CONFIRM_TRADE" and v == "Sail"
                    for _, k, v in result["legal"]["actions"]
                )
            elif phase == "receipt":
                play(desk, "CONFIRM_TRADE", "Sail")
            elif phase == "spur":
                play(desk, "BUILD_ROAD", edge)
            elif phase == "outpost":
                play(desk, "BUILD_SETTLEMENT", node)
            elif phase == "commission":
                city = (46 if target == 21 else 21) if wrong_city else target
                operate(desk, until_city=city)
            elif phase == "protect_delivery":
                if not desk.active.done():
                    operate(desk)
            elif phase not in (
                "amendment",
                "decision_record",
                "recovery",
                "final_handover",
            ):
                operate(desk)
            if episode is not EPISODE:
                from tasks.s4.single_site import SHIFTS, base_phase

                shift = base_phase(phase)
                if phase.endswith("_ledger") or (
                    shift in SHIFTS
                    and shift + "_ledger" not in episode.phases
                    and phase == shift
                ):
                    live = desk.active.state
                    desk.dispatch(
                        "notes",
                        {
                            "op": "write",
                            "name": shift,
                            "text": json.dumps(
                                {"position": live["position"], "hand": live["hand"]}
                            ),
                        },
                    )
            blocks.append(
                {
                    "index": index,
                    "phase": phase,
                    "table": "A",
                    "before": before,
                    "after": state_receipt(desk),
                    "first_tool": first,
                    "last_tool": desk.seq,
                }
            )
    meta = {
        "protocol": episode.protocol,
        "status": "complete",
        "arm": "single",
        "case": case,
        "opponent": opponent,
        "blocks": blocks,
        "image": image,
    }
    write(root / "manifest.json", meta)
    assert saw_sail_offer
    return replay(root, episode=episode), blocks


@unittest.skipUnless(os.getenv("S4_TEST_DOCKER"), "Docker opt-in")
class LongLeagueTest(unittest.TestCase):
    image = os.getenv("S4_LONG_TEST_IMAGE", "longworkmem-catan:1")

    def test_delayed_city_counterfactual_and_wrong_city(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            profiles = [
                witness(root / case, self.image, case, "strategic")
                for case in ("east", "east-capital")
            ]
            for (grade, blocks), city in zip(profiles, (21, 46), strict=True):
                self.assertEqual(grade["score"], 100)
                self.assertEqual(grade["first_city"], city)
                self.assertEqual(len(blocks), 16)
                self.assertGreaterEqual(grade["own_turns_advanced"], 6)
                self.assertEqual(grade["voluntary_reserve_breaches"], [])
            self.assertEqual(profiles[0][1][12]["before"], profiles[1][1][12]["before"])
            self.assertNotEqual(
                profiles[0][1][12]["after"], profiles[1][1][12]["after"]
            )
            grade, _ = witness(
                root / "wrong", self.image, "east-capital", "strategic", wrong_city=True
            )
            self.assertEqual(grade["checks"]["authorized_city"], [0, 20])
            self.assertEqual(grade["score"], 80)

    def test_operational_opponent_changes_actual_path(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _, cautious = witness(root / "cautious", self.image, "east", "cautious")
            _, strategic = witness(root / "strategic", self.image, "east", "strategic")
            self.assertEqual(cautious[0]["before"], strategic[0]["before"])
            self.assertNotEqual(cautious[12]["before"], strategic[12]["before"])
            for mode in ("cautious", "strategic"):
                with (root / mode / "trace/mcp.jsonl").open() as stream:
                    responses = [
                        e
                        for line in stream
                        for e in json.loads(line)["result"].get("responses", [])
                    ]
                flint_moves = [
                    e["value"]
                    for e in responses
                    if e["player"] == "Flint" and e["action"] == "MOVE_ROBBER"
                ]
                if mode == "cautious":
                    baseline = flint_moves
                else:
                    self.assertNotEqual(baseline, flint_moves)


class LongLeagueScoreTest(unittest.TestCase):
    def test_noop_and_false_stock_reserve(self):
        state = {"hand": {}, "finished": None, "completed_own_turns": 10}
        states = {"capital_market": state, "final_handover": state}
        self.assertEqual(evaluate("east", [], states)["score"], 0)
        spend = {
            "seq": 223,
            "action": "BUILD_SETTLEMENT",
            "value": 52,
            "wheat_after_spend": 1,
        }
        rows = [
            {"tool": "act", "phase": "outpost", "seq": 1, "result": {"event": spend}}
        ]
        result = evaluate("east", rows, states)
        self.assertEqual(result["checks"]["outpost"], [12, 12])
        self.assertEqual(result["checks"]["reserve_construction"], [0, 10])
        self.assertEqual(result["voluntary_reserve_breaches"], [223])
