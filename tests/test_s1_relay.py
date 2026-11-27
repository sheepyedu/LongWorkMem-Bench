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
