import json
import re
from pathlib import Path
import tempfile
import unittest

from s1.circuit import Circuit, audit
from s1.relay import WEIGHTS
from w1.gateway import MODEL


class CircuitTest(unittest.TestCase):
    def test_handover_carries_only_the_actual_bounded_note(self):
        c = Circuit(4, "A", 3, 2, version=1)
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

    def test_mixed_districts_preserve_same_schedule_and_assignment(self):
        a, b = [Circuit(13, v, 10, 2, 2, version=1) for v in "AB"]
        self.assertEqual(a.schedule, b.schedule)
        self.assertEqual(a.schedule, Circuit(13, "A", 10, 2, version=1).schedule)
        self.assertEqual([len(s.teams) for s in a.seasons.values()], [14] * 8 + [6] * 2)
        for i, (_, stage) in enumerate(a.schedule, 1):
            self.assertEqual(a.prompt(i) == b.prompt(i), stage != 1)
        with self.assertRaises(ValueError):
            Circuit(13, "A", 10, 2, 10, version=1)

    def test_public_paperwork_alone_solves_both_openings(self):
        from tests.test_s1_relay_reference import read_notices, rosters

        for arm in "AB":
            c = Circuit(411, arm, 10, 2, 2, version=1)
            archives, receipts = {}, []
            for t in range(1, 81):
                lines = c.prompt(t).splitlines()
                desk, stage = re.fullmatch(
                    r"总台第\d+轮｜(区\d+)第(\d+)班", lines[0]
                ).groups()
                stage = int(stage)
                orders = {}
                if stage == 1:
                    roster = {}
                    for line in lines[2:-1]:
                        team, *fields = line.split()
                        roster[team] = fields
                    archives[desk] = roster, [], {}
                elif stage in (2, 3, 6):
                    _, notices, withdrawn = archives[desk]
                    read_notices("\n".join(lines[1:-1]), notices, withdrawn, stage)
                else:
                    sheets = rosters(*archives[desk])
                    for item in lines[2].split("、"):
                        team, phase = item.split("/")
                        orders[team] = sheets[phase][team]
                receipts.append(c.receipt(t, {"orders": orders}))
            self.assertEqual(c.score(receipts)["total"], 100)

    def test_delayed_pair_and_score(self):
        a, b = [Circuit(4, arm, 9, 2, version=1) for arm in "AB"]
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
            history = [{"role": "system", "content": c.rules}]
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
                    score_version=2,
                    parser_version=3,
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
            manifest = run / "manifest.json"
            write(manifest, dict(json.loads(manifest.read_text()), model="gpt-6.1-sol"))
            for path in trace.glob("api-*.json"):
                packet = json.loads(path.read_text())
                packet["request"].update(model="gpt-6.1-sol", reasoning_effort="low")
                del packet["request"]["thinking"]
                packet["response"].update(model="gpt-6.1-sol")
                write(path, packet)
            self.assertEqual(audit(run)["total"], 0)
            packet["request"]["reasoning_effort"] = "high"
            write(path, packet)
            with self.assertRaisesRegex(ValueError, "low reasoning"):
                audit(run)
            packet["request"]["reasoning_effort"] = "low"
            write(path, packet)
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


class SingleCircuitTest(unittest.TestCase):
    def play_public(self, circuit):
        from tests.test_s1_relay_reference import read_notices, rosters

        archives, receipts = {}, []
        for turn, (desk, stage) in enumerate(circuit.schedule, 1):
            lines = circuit.prompt(turn).splitlines()
            command = {}
            if stage == 1:
                base = dict((team, fields) for team, *fields in
                            (line.split() for line in lines[2:-2]))
                archives[desk] = base, [], {}
            if stage in (2, 3, 6):
                _, notices, revoked = archives[desk]
                read_notices("\n".join(lines[1:-2]), notices, revoked, stage)
            sheets = rosters(*archives[desk])
            if lines[-1].startswith("登记任务"):
                phase, teams = re.fullmatch(r"登记任务：(\S+)，队号 ([\d、]+)。.*", lines[-1]).groups()
                command["register"] = {k: sheets[phase][k] for k in teams.split("、")}
            else:
                command["orders"] = {k: sheets[phase][k] for k, phase in
                                     (item.split("/") for item in lines[2].split("、"))}
            receipts.append(circuit.receipt(turn, command))
        return receipts

    def test_public_oracle_and_empty_outcomes_every_tier(self):
        for level in range(1, 5):
            for seed in (39107, 88469, 0):
                c = Circuit(seed, "A", 10, level, 2)
                receipts = self.play_public(c)
                result = c.score(receipts)
                self.assertEqual((result["total"], result["outcome_points"],
                                  result["registration_points"]), (100, 70, 30))
                self.assertEqual(len(result["groups"]), 8)
                self.assertEqual(result, c.score(receipts))
                for rec in receipts:
                    rec["booked"].clear()
                self.assertEqual(c.score(receipts)["total"], 30)
                self.assertEqual(c.score([c.receipt(t, {"note": "均已办理"})
                                          for t in range(1, 81)])["total"], 0)

    def test_one_field_costs_one_check_and_cannot_be_repaired_later(self):
        c = Circuit(13, "A", 10, 2, 2)
        records = self.play_public(c)
        team, fields = next(iter(records[0]["register"].items()))
        fields[0] = "错误"
        result = c.score(records)
        self.assertEqual(result["total"], round(100 - 7.5 / 80, 3))
        self.assertEqual(result["outcome_points"], 70)
        self.assertEqual(c.receipt(1, {"register": {team: fields[:2]}})["register"][team],
                         fields[:2] + [None, None])
        self.assertEqual(c.receipt(1, {"register": {"00": fields}})["register"], {})
        self.assertEqual(c.receipt(1, {"orders": {team: fields}})["booked"], {})
        with self.assertRaises(ValueError):
            c.receipt(1, {"register": []})
        for rec in records:
            if "register" in rec:
                rec["register"].clear()
        self.assertEqual(c.score(records)["total"], 70)
        with self.assertRaises(ValueError):
            c.score([records[1], records[0], *records[2:]])

    def test_replay_full_run_with_format_retry_and_tampered_evidence(self):
        from s1.circuit import read_command
        from s1.circuit_review import review

        c = Circuit(39107, "A", 10, 2, 2)
        receipts = self.play_public(c)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            trace = run / "trace"
            trace.mkdir()

            def write(path, value):
                path.write_text(json.dumps(value, ensure_ascii=False))

            calls = []
            history = [{"role": "system", "content": c.rules}]
            for t, receipt in enumerate(receipts, 1):
                prompt = c.prompt(t)
                (trace / f"prompt-{t}.txt").write_text(prompt)
                command = ({"register": receipt["register"]} if "register" in receipt
                           else {"orders": receipt["booked"]})
                attempts = [(t, prompt, json.dumps(command, ensure_ascii=False))]
                if t == 1:
                    invalid = "未提交"
                    with self.assertRaises(ValueError) as err:
                        read_command(invalid, 3)
                    retry = f"单据格式未接收：{err.exception}。请重交本轮单据。"
                    attempts = [(1, prompt, invalid), (81, retry, attempts[0][2])]
                calls.append([i for i, _, _ in attempts])
                for i, message, answer in attempts:
                    history.append({"role": "user", "content": message})
                    write(trace / f"api-{i:04}.json", {
                        "turn": i,
                        "request": {"model": MODEL, "thinking": {"type": "disabled"}, "messages": history},
                        "response": {"model": MODEL, "id": str(i), "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                                     "choices": [{"message": {"content": answer}}]}})
                    history.append({"role": "assistant", "content": answer})
                    write(trace / f"turn-{i}.jsonl", {"type": "result", "session_id": "test", "result": answer})
                write(run / f"receipt-{t}.json", receipt)
            meta = dict(seed=39107, variant="A", desks=10, level=2, qualifiers=2, calls=calls,
                        model=MODEL, session="test", score_version=2, parser_version=3, status="complete")
            write(run / "manifest.json", meta)
            score = audit(run)
            write(run / "grade.json", score)
            summary = review(run)
            self.assertEqual((summary["score"], summary["registration_points"], summary["calls"]),
                             (100, 30, 81))
            write(run / "grade.json", dict(score, registration_points=29))
            with self.assertRaisesRegex(ValueError, "stored grade"):
                review(run)
            write(run / "receipt-1.json", dict(receipts[0], register={}))
            with self.assertRaisesRegex(ValueError, "receipt mismatch"):
                audit(run)
            write(run / "receipt-1.json", receipts[0])
            packet = trace / "api-0081.json"
            forged = json.loads(packet.read_text())
            forged["request"]["messages"][-1]["content"] = "额外提示"
            write(packet, forged)
            with self.assertRaisesRegex(ValueError, "API prompt"):
                audit(run)
            packet.unlink()
            with self.assertRaisesRegex(ValueError, "missing provider"):
                audit(run)
            meta["calls"][0] = [1]
            write(run / "manifest.json", meta)
            with self.assertRaisesRegex(ValueError, "missing format retry"):
                audit(run)

    def test_omitting_each_turn_loses_exactly_its_weight(self):
        c = Circuit(88469, "A", 10, 2, 2)
        receipts = self.play_public(c)
        points = {1: 7.5, 2: 7.5, 3: 7.5, 4: 14, 5: 10.5, 6: 7.5, 7: 28, 8: 17.5}
        for t, (_, stage) in enumerate(c.schedule, 1):
            damaged = receipts.copy()
            damaged[t - 1] = c.receipt(t, {})
            self.assertEqual(c.score(damaged)["total"], 100 - points[stage] / 10)
