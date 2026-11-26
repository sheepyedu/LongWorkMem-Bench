from copy import deepcopy
from itertools import combinations
import json
import unittest

from s1.game import act, new_game, observe, open_turn, scout_notice


def find_cards(table, pattern):
    size = {"single": 1, "pair": 2, "flush": 3}[pattern]
    for combo in combinations(table["cards"], size):
        if pattern == "single" or (pattern == "pair" and combo[0]["rank"] == combo[1]["rank"]) or (
                pattern == "flush" and len({card["suit"] for card in combo}) == 1):
            return [card["id"] for card in combo]
    raise AssertionError(f"no {pattern} in {table}")


def empty_to(turn, variant="A", seed=71):
    state = new_game(variant, seed)
    for i in range(1, turn + 1):
        open_turn(state, i)
    return state


class LeagueGameTests(unittest.TestCase):
    def submit(self, state, op, **args):
        result = act(state, {"op": op, **args})
        self.assertTrue(result["ok"], result)
        return result

    def play(self, state, pattern, **args):
        table = observe(state)["table"]
        return self.submit(state, "play", pattern=pattern, cards=find_cards(table, pattern), **args)

    def reject(self, state, action):
        old = deepcopy(state)
        self.assertFalse(act(state, action)["ok"])
        self.assertEqual(old, state)

    def test_limited_scout_and_neutral_rental_display(self):
        states = [new_game(v, 51) for v in ("A", "B")]
        openings = [open_turn(s, 1) for s in states]
        self.assertEqual(openings[0].replace(scout_notice("A"), ""), openings[1].replace(scout_notice("B"), ""))
        for i, state in enumerate(states):
            v = ("A", "B")[i]
            self.assertIn(scout_notice(v), openings[i])
            self.assertNotIn(scout_notice(v), json.dumps(observe(state), ensure_ascii=False))
        for turn in range(2, 8):
            self.assertEqual(*[open_turn(s, turn) for s in states])
            self.assertEqual(*[observe(s) for s in states])
            self.assertEqual(*[act(s, {"op": "rules"}) for s in states])
        self.assertFalse(observe(states[0])["entry"]["locked"])
        self.assertNotIn("rental_points", observe(states[0]))
        with self.assertRaises(ValueError):
            open_turn(states[0], 1)

    def test_standard_optima_and_reproducible_seeds(self):
        fixtures = set()
        for seed in range(12):
            for variant in ("A", "B"):
                for gear in ("pair_repeat", "pair_once", "flush_repeat", "flush_once", "none"):
                    state = empty_to(7, variant, seed)
                    hands = observe(state)["entry"]["rental_hands"]
                    fixtures.add(json.dumps(hands))
                    for cards in hands:
                        for pattern in ("pair", "flush"):
                            self.assertTrue(find_cards({"cards": cards}, pattern))
                    self.submit(state, "draft", seat="standard", gear=gear)
                    self.submit(state, "lock")
                    self.reject(state, {"op": "lock"})
                    self.reject(state, {"op": "draft", "seat": "standard", "gear": "none"})
                    open_turn(state, 8)
                    surviving = "flush" if variant == "A" else "pair"
                    expected = 8 if not gear.startswith(surviving) else 16 if gear.endswith("repeat") else 15
                    self.assertEqual(observe(state)["rental_points"], expected)
        self.assertEqual(12, len(fixtures))

    def test_bad_input_and_swap_are_atomic(self):
        state = empty_to(2)
        for action in (None, [], {}, {"op": []}, {"op": "shell"}, {"op": "pay"},
                       {"op": "play", "pattern": {}, "cards": []},
                       {"op": "play", "pattern": "pair", "cards": ["c1", "c1"]},
                       {"op": "play", "pattern": "single", "cards": [["c1"]]},
                       {"op": "play", "pattern": "single", "cards": ["c1"], "tonic": 1},
                       {"op": "note", "path": "/anything", "text": "x"}):
            self.reject(state, action)
        before = observe(state)["table"]
        receipt = self.submit(state, "discard", card="c2")
        after = receipt["table"]
        self.assertEqual((after["hand"], after["earned"]), (1, 0))
        self.assertEqual(after["cards"][1], before["spare"])
        self.assertIsNone(after["spare"])
        self.reject(state, {"op": "discard", "card": "c1"})
        self.play(state, "single")
        self.assertIsNone(observe(state)["table"]["spare"])
        self.play(state, "single")
        self.assertEqual(observe(state)["results"][-1], {"match": "main1", "points": 2, "qualified": False})

    def test_full_seasons_have_real_resources_and_matching_receipts(self):
        for variant in ("A", "B"):
            family = "flush" if variant == "A" else "pair"
            state = empty_to(1, variant)
            self.submit(state, "note", text="尾款2")
            self.submit(state, "practice", pattern="flush", cards=["c1", "c3", "c4"])
            open_turn(state, 2)
            for _ in range(2):
                self.play(state, "pair")
            self.submit(state, "reward", choice="red5" if family == "flush" else "gold7")
            open_turn(state, 3)
            self.assertEqual(len(observe(state)["table"]["cards"]), 6)
            for _ in range(2):
                self.play(state, "pair")
            self.submit(state, "reserve", choice="tonic")
            open_turn(state, 4)
            self.assertEqual(len(observe(state)["table"]["cards"]), 5)
            for _ in range(2):
                self.assertEqual(self.play(state, "flush")["points"], 8)
            open_turn(state, 5)
            self.assertEqual(self.play(state, "flush")["points"], 4)
            self.assertTrue(self.play(state, "pair")["qualified"])
            open_turn(state, 6)
            self.submit(state, "claim")
            self.reject(state, {"op": "claim"})
            self.submit(state, "buy", gear=family + "_repeat")
            self.assertEqual(state["cash"], 3)
            open_turn(state, 7)
            self.assertEqual(self.submit(state, "read_note")["note"], "尾款2")
            self.reject(state, {"op": "draft", "seat": "private", "gear": "pair_once"})
            self.submit(state, "draft", seat="private", gear=family + "_repeat")
            self.submit(state, "draft", seat="standard", gear=family + "_once")
            self.submit(state, "lock")
            self.assertIsNone(state["standard_score"])
            open_turn(state, 8)
            self.reject(state, {"op": "pay"})
            self.assertEqual(state["standard_score"], 15)
            self.play(state, family, tonic=True)
            self.reject(state, {"op": "play", "pattern": family,
                                "cards": find_cards(observe(state)["table"], family), "tonic": True})
            self.assertEqual(self.play(state, family)["match_points"], 23)
            self.play(state, family)
            self.assertEqual(self.play(state, family)["match_points"], 16)
            self.assertEqual(self.submit(state, "pay")["cash"], 1)
            self.reject(state, {"op": "pay"})
            unchanged = json.loads(json.dumps(state))
            self.assertEqual(observe(state), observe(unchanged))

    def test_incomplete_stages_do_not_block_new_commissions(self):
        state = empty_to(8)
        self.assertIsNone(state["locked"])
        self.assertIsNone(state["standard_score"])
        self.assertEqual(observe(state)["table"]["match"], "free1")
        for _ in range(4):
            self.play(state, "single")
        self.assertEqual(self.submit(state, "pay")["cash"], 3)
        self.assertFalse(any(e["kind"] == "lock" for e in state["events"]))

    def test_notes_and_observations_are_independent_and_detached(self):
        state = empty_to(7)
        self.submit(state, "note", text="草案")
        self.assertEqual(self.submit(state, "read_note")["note"], "草案")
        self.reject(state, {"op": "note", "text": "x" * 10001})
        view = observe(state)
        view["entry"]["rental_hands"][0][0]["rank"] = -100
        view["entry"]["drafts"]["standard"] = "bad"
        self.assertNotEqual(observe(state)["entry"], view["entry"])
