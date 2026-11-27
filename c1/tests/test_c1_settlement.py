import json
import tempfile
import unittest
from pathlib import Path

from c1 import settlement as world
from c1.settlement_grade import ledger, matches
from c1.settlement_reference import solve


class SettlementTests(unittest.TestCase):
    def test_all_deadlines_alternate_implementation_and_pairing(self):
        for level in (1, 2):
            with tempfile.TemporaryDirectory() as tmp:
                for v in ("A", "B"):
                    work = Path(tmp) / v
                    inp = work / "input"
                    for turn in range(1, 7):
                        world.release(work, turn, v, 119, level)
                        if turn == 4:
                            continue
                        plan = json.loads(
                            (inp / "jobs" / f"{world.NAMES[turn - 1]}.json").read_text()
                        )
                        expected = ledger(inp, plan)
                        alternate = solve(inp, plan)
                        for field in expected:
                            self.assertTrue(
                                matches(alternate, expected, field),
                                (level, v, turn, field),
                            )
                    for p in (inp / "jobs").glob("archive-*.json"):
                        plan = json.loads(p.read_text())
                        exp = ledger(inp, plan)
                        got = solve(inp, plan)
                        self.assertTrue(all(matches(got, exp, f) for f in exp))
                a, b = (Path(tmp) / v / "input" for v in ("A", "B"))
                differences = [
                    p.relative_to(a).as_posix()
                    for p in a.rglob("*")
                    if p.is_file()
                    and p.read_bytes() != (b / p.relative_to(a)).read_bytes()
                ]
                self.assertEqual(differences, ["handover.txt"])
                plan = json.loads((a / "jobs/close.json").read_text())
                self.assertNotEqual(ledger(a, plan)["audit"], ledger(b, plan)["audit"])

    def test_semantic_rows_preserve_multiplicity_and_leading_zeroes(self):
        expected = {"accounts": [["ops", "01", 0], ["ops", "1", 3]]}
        self.assertTrue(
            matches({"accounts": expected["accounts"][::-1]}, expected, "accounts")
        )
        self.assertFalse(
            matches({"accounts": expected["accounts"][:1] * 2}, expected, "accounts")
        )

    def test_signed_deliveries_and_blind_reruns(self):
        import os
        import shutil
        import subprocess
        from unittest.mock import patch
        from c1 import reserve, reserve_reference, settlement_reference
        from c1.grade_evidence import Probes
        from c1.runstate import freeze
        from c1.settlement_grade import grade

        def reference_command(_probe, work, command):
            # Only this known reference file is executed in the fast unit test.
            result = subprocess.run(command.split(), cwd=work, capture_output=True)
            return result.stderr.decode() if result.returncode else ""

        with tempfile.TemporaryDirectory(dir=os.getenv("C1_TEST_ROOT")) as tmp:
            run = Path(tmp) / "run"
            work = Path(tmp) / "desk"
            for name in ("input", "project", "out", "data", "notes", "scratch"):
                (work / name).mkdir(parents=True)
            run.mkdir()
            (run / "manifest.json").write_text(
                json.dumps(
                    dict(
                        mode="settlement",
                        status="complete",
                        seed=77,
                        variant="B",
                        level=3,
                        dispatch_window=3,
                    )
                )
            )
            shutil.copyfile(settlement_reference.__file__, work / "project/settle.py")
            shutil.copyfile(reserve_reference.__file__, work / "project/reserve.py")
            for turn, name in enumerate((*world.NAMES, "guarantee"), 1):
                world.release(work, turn, "B", 77, 3)
                if turn in reserve.STAGES:
                    shutil.copyfile(
                        work / "input" / reserve.NOTICE,
                        work / "project" / f"notice-{turn}.csv",
                    )
                inp = work / "input"
                if turn == 2:
                    (work / "project/authority.txt").write_text(
                        (inp / "handover.txt").read_text().split("由 ")[1].split()[0]
                    )
                if turn == 3:
                    (inp / "handover.txt").unlink()
                if turn == 7:
                    self.assertFalse((inp / reserve.NOTICE).exists())
                    cmd = "python3 project/reserve.py input out/guarantee.json"
                    self.assertEqual(reference_command(None, work, cmd), "")
                elif turn == 4:
                    rows = [
                        json.loads(line)
                        for line in (inp / "incident.jsonl").read_text().splitlines()
                    ]
                    rows.sort(key=lambda r: (r["attempt"], r["stamp"]))
                    latest = {(r["site"], r["job"]): r for r in rows}
                    incidents = [
                        [*k, r["attempt"]]
                        for k, r in latest.items()
                        if r["result"] == "failed"
                    ]
                    (work / "out/incident.json").write_text(json.dumps(incidents))
                else:
                    plans = [inp / "jobs" / f"{name}.json"]
                    if turn == 6:
                        plans.extend((inp / "jobs").glob("archive-*.json"))
                    for plan in plans:
                        cmd = f"python3 project/settle.py input input/jobs/{plan.name} out/{plan.name}"
                        self.assertEqual(reference_command(None, work, cmd), "")
                freeze(work, run / "dispatch" / str(turn))
                freeze(work, run / "snapshots" / str(turn))
            from contextlib import nullcontext

            executor = (
                nullcontext()
                if os.getenv("C1_TEST_DOCKER") == "1"
                else patch.object(Probes, "command", reference_command)
            )
            with executor:
                manifest_path = run / "manifest.json"
                original = manifest_path.read_text()
                public = json.loads(original)
                public.update(protocol="public-v1", withdraw_handover=True, dispatch_window=None)
                manifest_path.write_text(json.dumps(public))
                score = grade(run)
                self.assertEqual(score["total"], 100)
                self.assertEqual(score["row_differences"], {})
                manifest_path.write_text(original)
                self.assertEqual(grade(run)["total"], 100)
                (run / "dispatch/4/out/incident.json").write_bytes(b"\xffbad")
                (run / "dispatch/6/out/close.json").write_text("null")
                late = grade(run)
                self.assertEqual(late["repaired"]["total"], 100)
                self.assertEqual(late["dispatch"]["checks"]["incident.latest"][0], 0)
                self.assertLess(late["total"], 100)
                (run / "snapshots/6/project/settle.py").write_text("pass")
                self.assertEqual(grade(run)["repaired"]["checks"]["rerun.0"][0], 0)
                for checkpoint in (run / "dispatch", run / "snapshots"):
                    for file in checkpoint.glob("*/out/*.json"):
                        file.write_text("{}")
                    for cli in checkpoint.glob("*/project/*.py"):
                        cli.write_text("pass")
                self.assertEqual(grade(run)["total"], 0)

    def test_duplicate_decision_cannot_receive_reversal_credit(self):
        from c1.settlement_compare import audit_map

        self.assertEqual(
            audit_map({"audit": [["a", "posted"], ["a", "denied"], [None, 2]]}),
            {"a": None},
        )
        self.assertEqual(audit_map({"audit": {}}), {})

    def test_archived_mandates_and_signer_change_independent_decisions(self):
        import shutil
        from c1 import reserve, reserve_reference
        from c1.reserve_grade import expected

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            project = work / "project"
            project.mkdir()
            for turn in range(1, 8):
                world.release(work, turn, "B", 149, 3)
                if turn in reserve.STAGES:
                    shutil.copyfile(
                        work / "input" / reserve.NOTICE, project / f"notice-{turn}.csv"
                    )
            a, b = world.generate(149, 2, "B")[3]
            rows = reserve.requests(149, a, b, 0)
            for signer in (a, b):
                (project / "authority.txt").write_text(signer)
                actual = reserve_reference.settle(project, work / "input")
                oracle = expected(149, signer, rows)
                for field in oracle:
                    self.assertTrue(matches(actual, oracle, field))
            self.assertNotEqual(expected(149, a, rows)["posted"], oracle["posted"])
            (project / "notice-1.csv").unlink()
            changed = reserve_reference.settle(project, work / "input")
            self.assertNotEqual(changed["decisions"], actual["decisions"])
            self.assertLess(len(changed["posted"]), len(actual["posted"]))

    def test_second_authorized_recall_is_duplicate_without_another_debit(self):
        from c1.settlement_diagnostics import add_second_recall

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for turn in range(1, 7):
                world.release(work, turn, "A", 31, 2)
            inp = work / "input"
            plan = json.loads((inp / "jobs/close.json").read_text())
            before = ledger(inp, plan)
            eid = add_second_recall(inp, plan)
            after = solve(inp, plan)
            self.assertEqual(dict(after["audit"])[eid], "duplicate")
            self.assertTrue(matches(after, before, "lots"))
            self.assertTrue(matches(after, before, "accounts"))

    def test_budget_stop_preserves_delivered_work_and_not_future_credit(self):
        from c1.settlement_grade import checkpoint_path

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "partial/5").mkdir(parents=True)
            (run / "trace").mkdir()
            m = {"status": "budget_exhausted", "turns": [{}] * 4, "dispatch_window": 2}
            self.assertEqual(checkpoint_path(run, m, "snapshots", 5), run / "partial/5")
            self.assertEqual(checkpoint_path(run, m, "dispatch", 5), run / "partial/5")
            (run / "trace/tools-5.jsonl").write_text("{}\n{}\n")
            self.assertEqual(checkpoint_path(run, m, "dispatch", 5), run / "dispatch/5")
            self.assertEqual(
                checkpoint_path(run, m, "snapshots", 6), run / "snapshots/6"
            )
