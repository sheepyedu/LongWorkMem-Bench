import json
import unittest

from tasks.s4.schedule import PHASES
from tasks.s4.scoring import filed_after_close, grade


def event(seq, action, value=None, player="You", **extra):
    return {"seq": seq, "action": action, "value": value, "player": player, **extra}


def evaluate(events=None, reserves=None):
    states = {
        p: {"hand": {}, "finished": None, "completed_own_turns": 0} for p in PHASES
    }
    states["market"]["hand"] = reserves or {}
    return grade([], states, events or {})


def trade(seq, player="You", partner="Ash", give=None, take=None):
    return event(
        seq,
        "CONFIRM_TRADE",
        {"partner": partner, "give": give or {"WOOD": 1}, "take": take or {"BRICK": 1}},
        player,
    )


class Checkpoints(unittest.TestCase):
    def test_noop_and_financing_bounds(self):
        self.assertEqual(evaluate()["score"], 0)
        for hand, points in (
            ({"ORE": 10}, 12),
            ({"WHEAT": 10}, 6),
            ({"ORE": 3, "WHEAT": 3}, 16.5),
            ({"ORE": 3, "WHEAT": 4}, 18),
        ):
            with self.subTest(hand=hand):
                self.assertEqual(
                    evaluate(reserves=hand)["checks"]["capital_stock"][0], points
                )

    def test_cargo_price_quantity_actor_and_first_settlement(self):
        bank = event(1, "MARITIME_TRADE", ["WOOD", "WOOD", None, None, "BRICK"])
        other = trade(1, "Flint", "Sail")
        responding = trade(2, "Flint", "You", {"BRICK": 1}, {"WOOD": 4})
        wrong = trade(2, take={"ORE": 1})
        for action, expected in (
            ([bank], (16, 8)),
            ([trade(1)], (16, 8)),
            ([other, responding], (16, 8)),
            ([other], (0, 0)),
            ([wrong, bank], (0, 0)),
            ([trade(1, take={"BRICK": 2})], (16, 0)),
            ([trade(1, give={"WOOD": 5})], (16, 0)),
            ([trade(1, give={"BRICK": 1}, take={"BRICK": 1})], (0, 0)),
            ([event(1, "ACCEPT_TRADE")], (0, 0)),
            ([trade(1, take={"BRICK": 1, "ORE": 1})], (0, 0)),
        ):
            with self.subTest(events=action):
                checks = evaluate({"clearing": action})["checks"]
                self.assertEqual((checks["received"][0], checks["terms"][0]), expected)

    def test_city_requires_node_and_time(self):
        for e, expected in (
            ({}, ("unobserved", 0)),
            ({"commission": [event(1, "BUILD_CITY", 22)]}, ("wrong", 0)),
            ({"commission": [event(1, "BUILD_CITY", 21, "Sail")]}, ("unobserved", 0)),
            ({"shift_7": [event(1, "BUILD_CITY", 21)]}, ("wrong", 0)),
            (
                {
                    "shift_7": [event(1, "BUILD_CITY", 22)],
                    "commission": [event(2, "BUILD_CITY", 21)],
                },
                ("wrong", 0),
            ),
            ({"commission": [event(1, "BUILD_CITY", 21)]}, ("correct", 22)),
        ):
            with self.subTest(events=e):
                g = evaluate(e)
                self.assertEqual(
                    (
                        g["authorization"]["decisions"]["city"]["outcome"],
                        g["checks"]["city_work"][0],
                    ),
                    expected,
                )

    def test_reserve_forced_losses_and_real_spending(self):
        events = {
            "shift_1": [event(1, "ROLL"), event(2, "DISCARD_RESOURCE", "WHEAT")],
            "shift_4": [
                event(3, "BUILD_CITY", 22, wheat_after_spend=1),
                event(4, "BUY_DEVELOPMENT_CARD", wheat_after_spend=0),
            ],
            "shift_7": [event(5, "BUILD_ROAD")],
            "shift_10": [event(6, "ROLL", "", "Ash")],
            "clearing": [
                trade(7, "Flint", "You", {"BRICK": 1}, {"WHEAT": 1})
                | {"wheat_after_spend": 0}
            ],
            "commission": [event(8, "BUILD_CITY", 21, wheat_after_spend=2)],
        }
        windows = evaluate(events)["reserve_windows"]
        self.assertEqual([w["points"] for w in windows], [2, 0, 2, 0, 0, 2])
        self.assertEqual(windows[1]["breaches"], [3, 4])
        self.assertEqual(windows[4]["breaches"], [7])

    def test_shift_count_excludes_opening_and_opponents(self):
        g = evaluate(
            {
                "shift_1_opening": [event(1, "END_TURN")],
                "shift_2": [event(2, "END_TURN", "", "Sail")],
                "shift_3": [event(3, "END_TURN")],
            }
        )
        self.assertEqual(g["checks"]["shifts"], [0.8, 12])

    def test_filing_frozen_after_close(self):
        phase = "shift_3"
        state = {"position": 30, "hand": {"WOOD": 1}}
        note = {
            "tool": "notes",
            "phase": phase,
            "args": {"name": phase, "op": "write", "text": json.dumps(state)},
            "result": {"ok": True},
        }
        close = {
            "tool": "act",
            "phase": phase,
            "args": {},
            "result": {"event": event(30, "END_TURN")},
        }
        delete = {**note, "args": {"op": "delete", "name": phase}}
        for rows, want in (
            ([close, note], True),
            ([note, close], False),
            ([close, note, delete], False),
            ([note], False),
            ([close, note, delete, note], True),
        ):
            self.assertEqual(filed_after_close(phase, rows, state), want)
        for body, want in (
            ('{ "hand":{"WOOD":1},"position":30,"comment":"closed"}', True),
            ('{"position":30,"hand":{"WOOD":true}}', False),
            ('{"position":30,"hand":{"WOOD":1,"ORE":0}}', False),
            ('{"position":28,"position":30,"hand":{"WOOD":1}}', False),
            ("invalid", False),
        ):
            n = {**note, "args": {**note["args"], "text": body}}
            self.assertEqual(filed_after_close(phase, [close, n], state), want)


class SettlementWindow(unittest.TestCase):
    def test_peer_confirms_beyond_public_response_page(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import Mock

        from tasks.s4.runtime import Desk

        for partner in ("You", "Ash"):
            with self.subTest(partner=partner), TemporaryDirectory() as tmp:
                table = Mock()
                table.done.return_value = False
                table.dispatch.return_value = {
                    "event": event(2, "ACCEPT_TRADE"),
                    "responses": [
                        event(i, "REJECT_TRADE", player="Ash") for i in range(3, 15)
                    ],
                    "more_events": True,
                    "state": {"position": 15},
                }
                table.request.return_value = {
                    "events": [trade(15, "Flint", partner, {"BRICK": 1}, {"WOOD": 1})]
                }
                desk = Desk(table, Path(tmp))
                desk.start("clearing")
                receipt = desk.dispatch("act", {"position": 1, "choice": 1})
                self.assertEqual(receipt["segment_done"], partner == "You")
                self.assertEqual(len(receipt["responses"]), 12)
                if partner == "You":
                    self.assertIn(
                        "error", desk.dispatch("act", {"position": 15, "choice": 1})
                    )
