import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.s4.audit import compaction_precedes_task
from tasks.s4.continuation import run
from tasks.s4.single_site import EXTENDED, FORMAL, score

from .test_long_league import witness


def action(phase, seq, name, value, **fields):
    return {
        "phase": phase,
        "tool": "act",
        "result": {"event": {"seq": seq, "action": name, "value": value, **fields}},
    }


class ReserveTests(unittest.TestCase):
    def test_native_summary_must_be_adopted_before_real_work(self):
        native = [{"subtype": "compact_boundary"}]
        request = {
            "messages": [
                {
                    "role": "user",
                    "content": "CRITICAL: Respond with TEXT ONLY. Summarize.",
                }
            ]
        }
        reply = {
            "choices": [{"message": {"content": "<summary>retained history</summary>"}}]
        }
        users = [
            {
                "role": "user",
                "content": "This session is being continued: retained history",
            },
            {"role": "user", "content": "new work order"},
        ]
        following = {"messages": users}
        self.assertTrue(
            compaction_precedes_task(
                native, request, reply, following, "new work order"
            )
        )
        self.assertFalse(
            compaction_precedes_task([], request, reply, following, "new work order")
        )
        self.assertFalse(
            compaction_precedes_task(
                native, request, reply, following, "different work order"
            )
        )
        self.assertFalse(
            compaction_precedes_task(
                native, request, reply, {"messages": users[-1:]}, "new work order"
            )
        )

    def test_other_site_cannot_start_a_formal_run(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archive-only-node"
            with self.assertRaisesRegex(ValueError, "Unsupported run condition"):
                run(
                    dest,
                    "single",
                    "east-capital",
                    "strategic",
                    None,
                    None,
                    None,
                    episode=FORMAL,
                )
            self.assertFalse(dest.exists())

    def test_noop_saving_forced_loss_and_repeated_breaches(self):
        states = {
            phase: {"hand": {}, "position": 10, "completed_own_turns": 10}
            for phase in FORMAL.phases
        }
        empty = score("east", [], states)
        self.assertEqual(empty["score"], 0)
        self.assertEqual(empty["authorization"]["observed"], 0)
        work = [
            action("mobilize", 1, "BUILD_ROAD", [16, 21]),
            action("spur", 2, "BUILD_ROAD", [6, 23]),
            action("supply_turn", 3, "ROLL", [1, 6]),
            action("supply_turn", 4, "DISCARD_RESOURCE", "WHEAT"),
        ]
        saved = score("east", work, states)
        self.assertEqual(saved["checks"]["reserve"], [6, 12])
        self.assertEqual(
            saved["authorization"]["decisions"]["route"]["outcome"], "wrong"
        )
        self.assertEqual(saved["checks"]["survey_spur_built"], [8, 8])
        work.extend(
            [
                action(
                    "supply_turn",
                    n,
                    "MARITIME_TRADE",
                    ["WHEAT"] * 4 + ["ORE"],
                    wheat_after_spend=0,
                )
                for n in (5, 6)
            ]
        )
        broken = score("east", work, states)
        self.assertEqual(broken["checks"]["reserve"], [4, 12])
        self.assertEqual(broken["reserve_windows"][2]["breach_events"], [5, 6])


@unittest.skipUnless(os.getenv("S4_TEST_DOCKER"), "Docker opt-in")
class LengthTests(unittest.TestCase):
    def test_same_work_and_legal_city_choices(self):
        image = os.getenv("S4_LONG_TEST_IMAGE", "longworkmem-catan:1")
        with TemporaryDirectory() as tmp:
            results = []
            for ep in (FORMAL, EXTENDED):
                grade, blocks = witness(
                    Path(tmp) / ep.protocol, image, "east", "strategic", episode=ep
                )
                self.assertEqual(grade["score"], 100)
                self.assertEqual(grade["authorization"]["correct"], 2)
                self.assertTrue(all(grade["inventory_filings"].values()))
                results.append({b["phase"]: b for b in blocks})
            a, b = results
            self.assertEqual((len(a), len(b)), (16, 24))
            self.assertEqual(a["commission"]["before"], b["commission"]["before"])
            for phase in a:
                self.assertEqual(a[phase]["after"], b[phase]["after"])
            grade, _ = witness(
                Path(tmp) / "wrong",
                image,
                "east",
                "strategic",
                wrong_city=True,
                episode=FORMAL,
            )
            self.assertEqual(grade["score"], 100)
            self.assertEqual(grade["authorization"]["correct"], 1)
