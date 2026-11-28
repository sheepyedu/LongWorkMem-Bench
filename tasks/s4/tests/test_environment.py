import json
import os
import subprocess
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.s4.engine import connect
from tasks.s4.grade import TARGET_EDGE, TRADE_CAP, evaluate_table
from tasks.s4.pilot import scouting
from tasks.s4.tools import TOOLS, Table, broker


@unittest.skipUnless(
    os.environ.get("S4_TEST_DOCKER"), "Docker engine integration is opt-in"
)
class CatanEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        d = Path(self.stack.enter_context(TemporaryDirectory()))
        self.eng = self.stack.enter_context(connect())
        self.table = Table(self.eng, d / "actions", d / "memory")

    def act(self, choice=None, **kwargs):
        return self.table.dispatch(
            "act",
            dict(
                position=self.table.state["position"],
                **({"choice": choice} if choice is not None else {}),
                **kwargs,
            ),
        )

    def choice(self, kind, predicate=lambda x: True):
        return next(
            a[0]
            for a in self.table.request("legal")["actions"]
            if a[1] == kind and predicate(a[2])
        )

    def test_real_mcp_round_trip_and_private_boundary(self):
        self.table.open("transfer-2")
        address, token = self.stack.enter_context(broker(self.table))
        requests = [
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
            [sys.executable, "-m", "tasks.s4.tools", address, token],
            input="".join(json.dumps(x) + "\n" for x in requests),
            text=True,
            capture_output=True,
            check=True,
        )
        tools, view, banned = map(json.loads, proc.stdout.splitlines())
        self.assertEqual(tools["result"]["tools"], TOOLS)
        text = view["result"]["content"][0]["text"]
        state = json.loads(text)["state"]
        self.assertEqual(len(state["tiles"]), 19)
        self.assertTrue(
            all(
                set(p)
                == {
                    "player",
                    "color",
                    "public_vp",
                    "resource_count",
                    "development_count",
                }
                for p in state["players"]
            )
        )
        self.assertEqual(
            json.loads(banned["result"]["content"][0]["text"]),
            {"error": "Unknown tool"},
        )
        self.assertNotIn("assigned_edge", text)

    def test_trade_responses_and_actual_confirmation_across_seats(self):
        for name in ("transfer-1", "transfer-2", "transfer-3"):
            self.table.open(name)
            initial = self.table.state
            response = self.act(give={"SHEEP": 1}, take={"BRICK": 1})
            self.assertEqual(initial["hand"], response["state"]["hand"])
            self.assertEqual(
                sorted(r["player"] for r in response["responses"]),
                ["Ash", "Flint", "Sail"],
            )
            self.assertEqual(
                [
                    r["player"]
                    for r in response["responses"]
                    if r["action"] == "ACCEPT_TRADE"
                ],
                ["Ash"],
            )
            confirm = self.choice("CONFIRM_TRADE", lambda x: x == "Ash")
            received = self.act(confirm)
            self.assertEqual(received["state"]["hand"]["BRICK"], 1)
            self.assertEqual(
                received["state"]["hand"].get("SHEEP", 0), initial["hand"]["SHEEP"] - 1
            )
            self.assertIn(
                "error",
                self.table.dispatch(
                    "act", {"position": initial["position"], "choice": confirm}
                ),
            )

    def test_schema_errors_do_not_change_board_and_notes_persist(self):
        self.table.open("transfer-2")
        start = self.table.state
        for args in (
            {"choice": True},
            {"choice": 999},
            {"give": {"SHEEP": -1}, "take": {"BRICK": 1}},
            {"give": {"SHEEP": 1}, "take": {"SHEEP": 1}},
            {"give": {"WHEAT": 998}, "take": {"BRICK": 1}},
            {},
        ):
            self.assertIn("error", self.act(**args))
            self.assertEqual(self.table.state, start)
        self.assertEqual(
            self.table.dispatch("look", {"after": "0"})["state"]["events"], []
        )
        self.assertIn(
            "error", self.table.dispatch("notes", {"op": "read", "name": "../grade.py"})
        )
        self.table.dispatch(
            "notes", {"op": "write", "name": "trade", "text": "one sale"}
        )
        self.table.open("update-2")
        self.assertEqual(
            self.table.dispatch("notes", {"op": "read", "name": "trade"})["text"],
            "one sale",
        )

    def test_scoring_witnesses_noop_and_wrong_history(self):
        self.assertIn("ACCEPT_TRADE", scouting(self.table, "game-1"))
        self.assertIn("REJECT_TRADE", scouting(self.table, "game-3"))
        for name, edge in TARGET_EDGE.items():
            initial = self.table.open(name)
            origin = initial["position"]
            self.assertTrue(
                all(
                    x[0] == 0
                    for x in evaluate_table(
                        name, self.table.request("end_state"), origin
                    ).values()
                )
            )
            self.act(self.choice("BUILD_ROAD", lambda x, edge=edge: sorted(x) == edge))
            self.assertEqual(
                sum(
                    v[0]
                    for v in evaluate_table(
                        name, self.table.request("end_state"), origin
                    ).values()
                ),
                10,
            )
            self.assertEqual(
                evaluate_table(
                    name, self.table.request("end_state"), origin, calibration=True
                ),
                {"assigned_edge": (6, 6)},
            )
        for name, cap in TRADE_CAP.items():
            origin = self.table.open(name)["position"]
            cost = {"SHEEP": "1"} if cap == 1 else {"SHEEP": 1, "WHEAT": 1}
            if cap == 2:
                rejected = self.act(give={"SHEEP": 1}, take={"BRICK": 1})
                self.assertFalse(
                    any(r["action"] == "ACCEPT_TRADE" for r in rejected["responses"])
                )
                self.assertEqual(
                    evaluate_table(name, self.table.request("end_state"), origin)[
                        "first_attempt"
                    ][0],
                    0,
                )
                self.table.open(name)
            self.act(give=cost, take={"BRICK": 1})
            self.act(self.choice("CONFIRM_TRADE"))
            self.act(self.choice("BUILD_ROAD"))
            self.assertEqual(
                sum(
                    v[0]
                    for v in evaluate_table(
                        name, self.table.request("end_state"), origin
                    ).values()
                ),
                10,
            )
            self.assertEqual(
                evaluate_table(
                    name, self.table.request("end_state"), origin, calibration=True
                ),
                {
                    "first_brick_attempt": (1, 1),
                    "purchase_cost": (4, 4),
                    "road_after_purchase": (1, 1),
                },
            )

    def test_replay_determinism(self):
        first = self.table.open("transfer-2")
        a = self.act(give={"SHEEP": 1}, take={"BRICK": 1})
        self.assertEqual(self.table.open("transfer-2"), first)
        self.assertEqual(self.act(give={"SHEEP": 1}, take={"BRICK": 1}), a)


class ScoreBoundaryTests(unittest.TestCase):
    def test_only_first_road_can_satisfy_corridor_in_review_variant(self):
        events = {
            "events": [
                {"seq": 1, "player": "You", "action": "BUILD_ROAD", "value": [5, 6]},
                {"seq": 2, "player": "You", "action": "BUILD_ROAD", "value": [10, 9]},
            ]
        }
        self.assertEqual(evaluate_table("route-1", events, 0)["assigned_edge"], (6, 6))
        self.assertEqual(
            evaluate_table("route-1", events, 0, first_road=True)["assigned_edge"],
            (0, 6),
        )
        self.assertEqual(
            evaluate_table("route-1", events, 0, calibration=True),
            {"assigned_edge": (0, 6)},
        )

    def test_brick_speed_and_price_are_independent(self):
        overpriced = {"give": {"WOOD": 1, "WHEAT": 1}, "take": {"BRICK": 1}}
        efficient = {"give": {"SHEEP": 1}, "take": {"BRICK": 1}}
        for actions, expected in (
            (
                [("OFFER_TRADE", overpriced), ("CONFIRM_TRADE", overpriced)],
                (1, 0, 1),
            ),
            (
                [
                    ("OFFER_TRADE", overpriced),
                    ("CANCEL_TRADE", None),
                    ("OFFER_TRADE", efficient),
                    ("CONFIRM_TRADE", efficient),
                ],
                (0, 4, 1),
            ),
            (
                [
                    ("OFFER_TRADE", {"give": {"SHEEP": 1}, "take": {"ORE": 1}}),
                    ("CANCEL_TRADE", None),
                    ("OFFER_TRADE", efficient),
                    ("CONFIRM_TRADE", efficient),
                ],
                (1, 4, 1),
            ),
        ):
            events = {
                "events": [
                    {"seq": i, "player": "You", "action": action, "value": value}
                    for i, (action, value) in enumerate(
                        [*actions, ("BUILD_ROAD", [1, 2])], 1
                    )
                ]
            }
            result = evaluate_table("transfer-2", events, 0, calibration=True)
            self.assertEqual(
                tuple(
                    result[k][0]
                    for k in (
                        "first_brick_attempt",
                        "purchase_cost",
                        "road_after_purchase",
                    )
                ),
                expected,
            )

    def test_wrong_player_late_action_and_prefix_do_not_count(self):
        events = {
            "events": [
                {"seq": 1, "player": "You", "action": "BUILD_ROAD", "value": [9, 10]},
                {"seq": 2, "player": "Ash", "action": "BUILD_ROAD", "value": [9, 10]},
                {"seq": 3, "player": "You", "action": "END_TURN", "value": None},
                {"seq": 4, "player": "You", "action": "BUILD_ROAD", "value": [9, 10]},
            ]
        }
        self.assertEqual(
            evaluate_table("route-1", events, 1),
            {"paved": (0, 4), "assigned_edge": (0, 6)},
        )
