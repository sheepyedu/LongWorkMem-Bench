import json
from pathlib import Path
import tempfile
import unittest

from s1.relay import LEVELS, PHASE, WEIGHTS, Season, decode, grade, submit
from s1.relay_pilot import evaluate


def from_archive(season, team, phase):
    """Second implementation: index valid receipts backwards at the historical cutoff."""
    end = dict((name, turn) for turn, name in PHASE.items())[phase]
    rows = list(reversed(season.notices))
    return [next((row.value for row in rows if row.team == team and row.field == i
                  and row.official and row.turn < end and row.scope in {phase, "全季"}
                  and not (row.number in season.withdrawn and season.withdrawn[row.number] < end)),
                 base) for i, base in enumerate(season.base[team])]


class RelayTest(unittest.TestCase):
    def test_all_tiers_and_paired_public_observations(self):
        for seed in range(30):
            for level in LEVELS:
                a, b = (Season(seed, level, v) for v in "AB")
                self.assertEqual(a.jobs, b.jobs)
                self.assertEqual(a.bulletins.keys(), b.bulletins.keys())
                self.assertNotEqual(a.bulletins[1], b.bulletins[1])
                self.assertEqual(a.notices, b.notices)
                self.assertEqual(a.withdrawn, b.withdrawn)
                for t in range(2, 9):
                    self.assertEqual(a.prompt(t, "", "relay"), b.prompt(t, "", "relay"))
                for season in (a, b):
                    receipts = {}
                    for t, rows in season.jobs.items():
                        orders = {k: from_archive(season, k, phase) for k, phase in rows}
                        receipts[str(t)] = submit(season, t, {"orders": orders}, "")
                    self.assertEqual(grade(season, receipts)["total"], 100)

    def test_stage_binding_partial_credit_and_note_capacity(self):
        season = Season(134, 2)
        rows = season.jobs[7]
        orders = {team: from_archive(season, team, phase) for team, phase in rows}
        team = rows[0][0]
        orders[team][1] = "11" if orders[team][1] != "11" else "12"
        orders["unknown"] = ["P1", "90", "松", "东"]
        receipt = submit(season, 7, {"note": "松"*500, "orders": orders}, "old")
        self.assertEqual(len(receipt["note"]), season.capacity)
        self.assertEqual(receipt["note_length"], 500)
        self.assertEqual(receipt["rejected"], ["unknown"])
        self.assertEqual(submit(season, 7, {}, "old")["note"], "old")
        result = grade(season, {"7": receipt})
        self.assertAlmostEqual(result["groups"]["7"], WEIGHTS[7] * (1 - 1 / (2 * len(rows))))
        self.assertEqual(result["groups"]["8"], 0)

    def test_receipts_come_from_cli_and_format_variations(self):
        self.assertEqual(decode('提交如下\n```json\n{"note":"松"}\n```'), {"note":"松"})
        for malformed in ['{"note":"一","note":"二"}', '[]', '```json\n{}\n```\n```json\n{}\n```']:
            with self.assertRaises(ValueError):
                decode(malformed)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "trace").mkdir()
            season = Season(134, 1)
            turns = []
            for turn in WEIGHTS:
                orders = {k: from_archive(season, k, phase) for k, phase in season.jobs[turn]}
                packet = {"orders": orders}
                (run / "trace" / f"turn-{turn}.jsonl").write_text(json.dumps(
                    {"type":"result","is_error":False,"result":json.dumps(packet)}))
                (run / f"receipt-{turn}.json").write_text(json.dumps(submit(season, turn, packet, "")))
                turns.append({"turn":turn,"calls":[turn]})
            (run / "manifest.json").write_text(json.dumps({"status":"complete","turns":turns,
                "condition":"current","seed":134,"level":1,"variant":"A"}))
            self.assertEqual(evaluate(run)["total"], 100)
            (run / "receipt-8.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "differs"):
                evaluate(run)


class CalibrationReviewTest(unittest.TestCase):
    def test_pairs_are_seed_weighted_and_incomplete_pairs_are_invalid(self):
        from s1.relay_review import compare
        reports = [dict(seed=seed, model=model, variant=arm, score=score, condition="relay",
                        level=2, flags=[])
                   for seed, gap in [(1, 5), (2, 11)]
                   for arm in "AB"
                   for model, score in [("deepseek-v4-1-flash-261017", 50 + gap), ("qwen3.8-flash", 50)]]
        paired = compare(reports)
        self.assertEqual(paired["gap"], 8)
        self.assertEqual(paired["seed_gaps"], [5, 11])
        self.assertEqual(paired["seed_bootstrap_95_pct"], [5, 11])
        for invalid in (reports[:-1], reports + reports[:1], [dict(reports[0], flags=["bad"])] + reports[1:]):
            with self.assertRaises(ValueError):
                compare(invalid)

    def test_history_labels_identify_counterfactual_fields(self):
        from s1.relay import Notice
        from s1.relay_review import dependency_groups
        season = Season(134, 1)
        team = season.teams[0]
        season.base[team] = ["F1", "55", "柳", "北"]
        season.notices = [Notice("D001", team, 0, "P4", "全季", 2, True),
                          Notice("D002", team, 1, "12", "邀请", 3, True),
                          Notice("D003", team, 3, "南", "全季", 6, True)]
        season.withdrawn = {"D001":6}
        def labels(turn, phase):
            return set(dependency_groups(season, dict(team=team, phase=phase, turn=turn,
                                                      expected=season.expected(team, phase))))
        self.assertEqual(labels(7, "决赛"), {("撤回后回退", 0), ("邀请专项到期", 1)})
        self.assertEqual(labels(8, "邀请"), {("历史截止", 0), ("历史截止", 3)})


class WarehouseTest(unittest.TestCase):
    def test_archive_is_stale_and_identical_across_counterfactuals(self):
        for level in LEVELS:
            for seed in (5, 15, 25):
                a,b=(Season(seed, level, v, "warehouse") for v in "AB")
                self.assertEqual(a.stock,b.stock)
                self.assertTrue(all(sum(x!=y for x,y in zip(a.stock[k], a.base[k]))==1 for k in a.teams))
                for turn in WEIGHTS:
                    self.assertEqual(a.prompt(turn,"","relay"),b.prompt(turn,"","relay"))
                    orders={k:from_archive(a,k,ph) for k,ph in a.jobs[turn]}
                    team=next(iter(orders))
                    orders[team][0]="未知"
                    rec=submit(a,turn,{"orders":orders},"")
                    self.assertEqual(rec["rejected"],[])
                    self.assertAlmostEqual(grade(a,{str(turn):rec})["groups"][str(turn)],
                                           WEIGHTS[turn]*(1-1/(2*len(orders))))
