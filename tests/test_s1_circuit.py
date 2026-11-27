import json
from pathlib import Path
import tempfile
import unittest

from s1.circuit import Circuit, RULES, audit
from s1.relay import WEIGHTS
from w1.gateway import MODEL


class CircuitTest(unittest.TestCase):
    def test_handover_carries_only_the_actual_bounded_note(self):
        c = Circuit(4, "A", 3, 2)
        mid = len(c.schedule) // 2
        note = "杉" * 5510
        rec = c.receipt(mid, {"note": note}, "handover")
        self.assertEqual(rec["memo_length"], 5510)
        self.assertEqual(rec["memo"], note[:5500])
        self.assertEqual(
            c.prompt(mid + 1, "handover", rec["memo"]).split("摘要：\n")[-1],
            note[:5500],
        )
        self.assertNotIn(note[:100], c.prompt(mid + 2, "handover", rec["memo"]))
        self.assertNotIn("memo", c.receipt(mid, {"note": note}))
        self.assertEqual(c.receipt(mid, {}, "handover")["memo"], "")

    def test_delayed_pair_and_score(self):
        a, b = [Circuit(4, arm, 9, 2) for arm in "AB"]
        self.assertEqual(a.schedule, b.schedule)
        self.assertEqual(len(a.schedule), 72)
        receipts = []
        for turn, (desk, stage) in enumerate(a.schedule, 1):
            self.assertEqual(a.prompt(turn) == b.prompt(turn), stage != 1)
            season = a.seasons[desk]
            orders = {
                k: season.expected(k, phase) for k, phase in season.jobs.get(stage, [])
            }
            receipts.append(a.receipt(turn, {"orders": orders}))
        self.assertEqual(a.score(receipts)["total"], 100)
        desk, _ = a.schedule[-1]
        opener = a.schedule.index((desk, 1))
        self.assertGreaterEqual(71 - opener, 55)
        receipts[-1]["booked"].clear()
        self.assertEqual(a.score(receipts)["total"], round(100 - WEIGHTS[8] / 9, 3))
        with self.assertRaises(ValueError):
            a.score(receipts[:-1])

    def test_replay_uses_actual_replies_and_provider_usage(self):
        c = Circuit(6, "A", 2, 1)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            trace = run / "trace"
            trace.mkdir()

            def write(p, d):
                p.write_text(json.dumps(d))

            calls = []
            history = [{"role": "system", "content": RULES}]
            for i in range(1, len(c.schedule) + 1):
                calls.append([i])
                prompt = c.prompt(i)
                history.append({"role": "user", "content": prompt})
                (trace / f"prompt-{i}.txt").write_text(prompt)
                write(
                    trace / f"turn-{i}.jsonl",
                    {"type": "result", "session_id": "test", "result": "{}"},
                )
                write(
                    trace / f"api-{i:04d}.json",
                    {
                        "turn": i,
                        "request": {
                            "model": MODEL,
                            "thinking": {"type": "disabled"},
                            "messages": history,
                        },
                        "response": {
                            "model": MODEL,
                            "id": str(i),
                            "choices": [{"message": {"content": "{}"}}],
                            "usage": {"prompt_tokens": i * 17, "completion_tokens": 2},
                        },
                    },
                )
                history.append({"role": "assistant", "content": "{}"})
                write(run / f"receipt-{i}.json", c.receipt(i, {}))
            write(
                run / "manifest.json",
                dict(
                    model=MODEL,
                    session="test",
                    seed=6,
                    variant="A",
                    level=1,
                    desks=2,
                    calls=calls,
                ),
            )
            result = audit(run)
            self.assertEqual(result["total"], 0)
            self.assertEqual(
                result["usage"]["first_submission_input"], sum(range(1, 17)) * 17
            )
            self.assertEqual(result["usage"]["peak_input"], 16 * 17)
            write(run / "receipt-9.json", {})
            with self.assertRaisesRegex(ValueError, "mismatch"):
                audit(run)


class SubmissionTest(unittest.TestCase):
    def test_unambiguous_bare_orders_and_prose(self):
        from s1.circuit import read_command

        orders = {"12": ["P1", "31", "杏", "西"]}
        self.assertEqual(
            read_command("已核对。\n" + json.dumps(orders), 2), {"orders": orders}
        )
        for text in [
            "```json\n{}\n```\n{}",
            "{} 和 {}",
            '{"ordres":{}}',
            '{"12":[], "12":[]}',
        ]:
            with self.assertRaises(ValueError):
                read_command(text, 2)
