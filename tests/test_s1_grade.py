"""Acceptance of alternate S1 strategies and independently localized scoring failures."""
from itertools import combinations
import json
from pathlib import Path
import tempfile
import unittest

from s1.game import act, new_game, observe, open_turn
from s1.grade import grade, grade_standard, standard_maximum


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cards_for(hand, pattern):
    size = {"pair": 2, "flush": 3, "single": 1}[pattern]
    for choice in combinations(hand, size):
        if pattern == "pair" and len({c["rank"] for c in choice}) != 1:
            continue
        if pattern == "flush" and len({c["suit"] for c in choice}) != 1:
            continue
        return [c["id"] for c in choice]
    raise AssertionError((pattern, hand))


def run_season(run, variant="A", seed=31, *, mode="natural", standard=None,
               free=None, first_return="pair", invite1="flush", pay=True, lock=True):
    """Use the actual actions and observations; no grading state is injected."""
    family = "flush" if variant == "A" else "pair"
    standard = standard or family + "_repeat"
    free = free or family + "_repeat"
    state = new_game(variant, seed)
    (run / "trace").mkdir(parents=True)
    (run / "snapshots").mkdir()
    write(run / "manifest.json", {"variant": variant, "seed": seed, "mode": mode, "status": "complete"})
    for turn in range(1, 9):
        open_turn(state, turn)
        if mode != "natural" and turn < 7:
            continue
        records = []

        def submit(**action):
            result = act(state, action)
            if result.get("ok") is not True:
                raise AssertionError(f"{action} -> {result}")
            records.append({"turn": turn, "tool": "act", "args": {"action": action}, "result": result})

        def play(pattern):
            table = observe(state)["table"]
            submit(op="play", pattern=pattern, cards=cards_for(table["cards"], pattern))

        if turn == 2:
            play("pair")
            play("pair")
            submit(op="reward", choice="red5" if variant == "A" else "gold7")
        elif turn == 3:
            play("pair")
            play("pair")
            submit(op="reserve", choice=family + "_once")
        elif turn == 4:
            play(invite1)
            play("flush")
        elif turn == 5:
            play(first_return)
            play("pair")
        elif turn == 6:
            submit(op="claim")
            submit(op="buy", gear=family + "_repeat")
        elif turn == 7:
            if mode == "natural":
                submit(op="draft", seat="private", gear=free)
            submit(op="draft", seat="standard", gear=standard)
            if lock:
                submit(op="lock")
        elif turn == 8:
            for _ in range(4):
                play(family)
            if pay:
                submit(op="pay")
        log = run / "trace" / f"tools-{turn}.jsonl"
        log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf8")
        write(run / "snapshots" / f"{turn}.json", state)
        if mode != "natural":
            break
    return grade(run)


class SeasonScoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_full_reference_and_equivalent_builds(self):
        for variant, family in (("A", "flush"), ("B", "pair")):
            for suffix, seed in (("_once", 17), ("_repeat", 31)):
                gear = family + suffix
                with self.subTest(variant=variant, gear=gear):
                    result = run_season(self.root / (variant + gear), variant, seed, standard=gear, free=gear)
                    self.assertTrue(result["strict_pass"], result)
                    self.assertEqual(result["total"], 100)

    def test_three_specific_errors_only_lose_their_own_items(self):
        result = run_season(self.root / "wrong", standard="pair_repeat",
                            first_return="flush", invite1="pair")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["total"], 53)
        self.assertEqual({i["id"] for i in result["items"] if not i["points"]},
                         {"invite1", "return_first", "standard"})

    def test_finishing_and_paying_does_not_require_winning(self):
        result = run_season(self.root / "failed-finals", free="none")
        self.assertEqual((result["valid"], result["total"]), (True, 80), result)
        unpaid = run_season(self.root / "unpaid", pay=False)
        self.assertEqual((unpaid["valid"], unpaid["total"]), (True, 95), unpaid)

    def test_unlocked_drafts_score_zero_but_empty_gear_can_play_and_pay(self):
        result = run_season(self.root / "draft-only", lock=False)
        self.assertEqual((result["valid"], result["total"]), (True, 50), result)

    def test_two_successful_standard_builds_per_version_across_seeds(self):
        from s1.grade import GEAR
        for seed in (2, 31, 177):
            scores = {}
            for variant in ("A", "B"):
                hands = new_game(variant, seed)["standard_hands"]
                scores[variant] = {g for g in GEAR if standard_maximum(hands, g, variant) >= 15}
                self.assertEqual(len(scores[variant]), 2)
            self.assertTrue(scores["A"].isdisjoint(scores["B"]))

    def test_controls_have_own_denominator_and_replay(self):
        for mode, variant, gear, points in (("reminder", "A", "flush_once", 30),
                                            ("current", "B", "flush_once", 0)):
            result = run_season(self.root / mode, variant, mode=mode, standard=gear)
            self.assertEqual((result["valid"], result["total"], result["max_score"]),
                             (True, points, 30), result)

    def test_cumulative_ledger_edits_and_missing_calls_are_detected(self):
        run = self.root / "bad"
        run_season(run)
        path = run / "snapshots/7.json"
        s = json.loads(path.read_text())
        s["events"][-1]["fake"] = "this text and the final answer cannot change a receipt"
        write(path, s)
        self.assertFalse(grade(run)["valid"])
        (run / "trace/tools-2.jsonl").write_text("")
        result = grade(run)
        self.assertTrue(any("replayed" in line for line in result["infrastructure_anomalies"]))
        self.assertFalse(next(i["points"] for i in result["items"] if i["id"] == "main1"))

    def test_malformed_json_and_nested_shapes_return_diagnostics(self):
        run = self.root / "bad-json"
        run_season(run)
        for raw in ('{"turn":2,"turn":1}', "[]", '{"x":NaN}', '{"dangling":'):
            (run / "snapshots/2.json").write_text(raw)
            result = grade(run)
            self.assertFalse(result["valid"], raw)
            self.assertEqual(len(result["items"]), 10)
        state = json.loads((run / "snapshots/7.json").read_text())
        state["standard_hands"] = [None, []]
        self.assertFalse(grade_standard(state, "A")["valid"])
        state["events"] = [None]
        self.assertFalse(grade_standard(state, "A")["valid"])

    def test_valid_stopped_run_preserves_frozen_items(self):
        run = self.root / "partial"
        run_season(run)
        meta = json.loads((run / "manifest.json").read_text())
        meta["status"] = "budget_exhausted"
        write(run / "manifest.json", meta)
        for turn in range(4, 9):
            (run / "snapshots" / f"{turn}.json").unlink()
        result = grade(run)
        self.assertEqual((result["valid"], result["total"]), (True, 15), result)

    def test_format_variants_and_receipt_corruption(self):
        run = self.root / "formats"
        run_season(run)
        for path in (run / "snapshots/7.json", run / "trace/tools-2.jsonl"):
            text = path.read_text().replace("\n", "\r\n")
            path.write_bytes(("\ufeff \r\n" + text).encode("utf-8"))
        self.assertTrue(grade(run)["strict_pass"])
        tool_file = run / "trace/tools-3.jsonl"
        rows = [json.loads(s) for s in tool_file.read_text().splitlines()]
        rows[0]["result"]["points"] = 999
        tool_file.write_text("".join(json.dumps(row) + "\n" for row in rows))
        result = grade(run)
        self.assertFalse(result["valid"])
        self.assertTrue(any("receipt differs" in issue for issue in result["infrastructure_anomalies"]))
        self.assertEqual(result["total"], 7)

    def test_missing_evidence_cannot_justify_later_totals(self):
        run = self.root / "missing-tools"
        run_season(run)
        (run / "snapshots/6.json").unlink()
        (run / "trace/tools-6.jsonl").unlink()
        result = grade(run)
        self.assertFalse(result["valid"])
        self.assertEqual(result["total"], 45)
