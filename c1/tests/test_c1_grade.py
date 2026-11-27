"""Negative controls for timing, artifact semantics, and independent replay."""
import csv
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from c1.grade import early_current, grade, grade_control, original_dispatcher, result_record
from c1.grade_evidence import Probes, Rows
from c1.reference import run_reference


BACKEND = "docker" if os.getenv("C1_TEST_DOCKER") == "1" else "seatbelt"


def changed(result):
    return {key: value["max"] - value["earned"] for key, value in result["checks"].items()
            if value["earned"] != value["max"]}


class EvidenceTests(unittest.TestCase):
    def test_missing_artifacts_and_failed_sandbox_are_distinguishable(self):
        with tempfile.TemporaryDirectory() as tmp, patch("c1.sandbox.shell", side_effect=RuntimeError("image missing")):
            result = grade(Path(tmp), "A", backend=BACKEND)
            self.assertIsNone(result["total"])
            self.assertFalse(result["valid"])
            self.assertEqual(result["infrastructure_errors"], ["sandbox unavailable: image missing"])
            self.assertIn("sandbox unavailable", result["checks"]["CP1.legacy"]["reason"])
            self.assertIn("failed.txt", result["checks"]["CP3.detour"]["reason"])
            json.dumps(result)

    def test_unshared_bind_mount_invalidates_even_an_apparently_successful_shell(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
                "c1.sandbox.shell", return_value={"status": 0, "output": ""}) as shell:
            result = grade_control(Path(tmp), "A", BACKEND)
            self.assertIsNone(result["total"])
            self.assertFalse(result["valid"])
            self.assertIn("read/write verification failed", result["infrastructure_errors"][0])
            self.assertEqual(shell.call_count, 1)

    def test_manifested_missing_snapshot_is_infrastructure_but_missing_product_is_scoreable(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "manifest.json").write_text('{"status":"complete","turns":[{"turn":9}]}')
            result = result_record(run, "B", Probes(BACKEND, run), {}, [9], 10)
            self.assertIsNone(result["total"])
            self.assertEqual(result["infrastructure_errors"], ["missing frozen snapshot(s) [9]"])
            (run / "snapshots/9").mkdir(parents=True)
            ok = result_record(run, "B", Probes(BACKEND, run), {}, [9], 10)
            self.assertEqual(ok["total"], 0)
            self.assertTrue(ok["valid"])

    def test_docker_regrading_uses_the_recorded_image_digest(self):
        with tempfile.TemporaryDirectory() as tmp, patch("c1.sandbox.shell") as shell:
            run = Path(tmp)
            image = "sha256:" + "f" * 64
            (run / "manifest.json").write_text(json.dumps({"image": image}))
            probe = Probes("docker", run)
            probe.execute(run, "true", 30)
            shell.assert_called_once_with(run, "true", backend="docker", timeout=30, image=image)

    def test_replay_preserves_the_dispatcher_released_to_this_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            snapshot = run / "snapshots/12"
            (snapshot / "input").mkdir(parents=True)
            archived = snapshot / "input/batch.py"
            archived.write_bytes(b"def main(): return 12\n")
            digest = hashlib.sha256(archived.read_bytes()).hexdigest()
            (run / "manifest.json").write_text(json.dumps({"source_hashes": {"c1/starter/batch.py": digest}}))
            inputs = run / "replay-inputs"
            inputs.mkdir()
            (inputs / "batch.py").write_text("def dispatch(): return 7\n")
            probes = Probes(BACKEND, run)
            self.assertEqual(original_dispatcher(run, snapshot, inputs, probes), digest)
            self.assertEqual((inputs / "batch.py").read_bytes(), archived.read_bytes())
            archived.write_bytes(b"changed")
            self.assertIsNone(original_dispatcher(run, snapshot, inputs, probes))
            self.assertIn("recorded source hash", probes.infrastructure[0])

    def test_early_history_projection_verifies_all_rows_and_multiplicities(self):
        history = [("A", "0017", 1, "dispatch", "open"), ("A", "0017", 3, "ops", "closed")]
        ledger = Mock()
        ledger.all_versions.return_value = history
        original = Rows(history[::-1])
        self.assertEqual(early_current(original, ledger).values, history[1:])
        for invalid in ([*history, history[0]], [(*history[0][:3], "wrong", "open"), history[1]],
                        [*history, ("B", "99", 1, "x", "open")]):
            self.assertEqual(early_current(Rows(invalid), ledger).values, invalid)

    def test_semantic_reader_rejects_duplicates_invalid_types_and_external_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "rows").write_text('[{"revision":true}]')
            self.assertTrue(Rows.read(work, "rows", ("revision",), "json").error)
            (work / "rows").write_text("dept,count,count\nx,1,1\n")
            self.assertTrue(Rows.read(work, "rows", ("dept", "count"), "csv").error)
            (work / "link").symlink_to(work / "rows")
            self.assertTrue(Rows.read(work, "link", (), "text").error)
            self.assertFalse(Rows([("A",), ("A",)]).match([("A",)])[0])


@unittest.skipUnless(platform.system() == "Darwin" or BACKEND == "docker",
                     "requires macOS Seatbelt or C1_TEST_DOCKER=1")
class GradeControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory(dir=os.getenv("C1_TEST_ROOT"))
        cls.addClassCleanup(tmp.cleanup)
        cls.base = run_reference(Path(tmp.name) / "base", "B", backend=BACKEND)

    def copy_run(self):
        tmp = tempfile.TemporaryDirectory(dir=os.getenv("C1_TEST_ROOT"))
        self.addCleanup(tmp.cleanup)
        return Path(shutil.copytree(self.base, Path(tmp.name) / "changed"))

    def test_wrong_policy_costs_only_its_three_preregistered_checks(self):
        result = grade(self.base, "A", backend=BACKEND)
        self.assertEqual(changed(result), {"CP4.decision": 6, "CP4.audit": 4, "CP5.policy": 4})
        self.assertEqual(result["total"], 86)
        self.assertEqual(result["dependency"]["event_ids"], ["change-201"])

    def test_short_control_uses_only_the_frozen_r9(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            shutil.copytree(self.base / "snapshots/9", run / "snapshots/9")
            self.assertEqual(grade_control(run, "B", BACKEND)["total"], 10)
            self.assertEqual(grade_control(run, "A", BACKEND)["total"], 0)
            with closing(sqlite3.connect(run / "snapshots/9/data/tickets.sqlite")) as db, db:
                db.execute("DELETE FROM events WHERE event_id='change-202'")
            result = grade_control(run, "B", BACKEND)
            self.assertEqual(changed(result), {"CP4.audit": 4})
            self.assertEqual(result["checks"]["CP4.decision"]["earned"], 6)

    def test_r9_scope_requires_unchanged_current_even_when_audit_decisions_are_right(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            snapshot = run / "snapshots/9"
            shutil.copytree(self.base / "snapshots/9", snapshot)
            with closing(sqlite3.connect(snapshot / "data/tickets.sqlite")) as db, db:
                db.execute("UPDATE events SET dept='quality' WHERE event_id='field-007'")
            result = grade_control(run, "B", BACKEND)
            self.assertEqual(changed(result), {"CP4.decision": 2})

    def test_stage_local_damage_does_not_spread_to_later_frozen_checks(self):
        run = self.copy_run()
        snapshots = run / "snapshots"
        (snapshots / "2/out/quarantine.csv").write_text("id,number,dept,status\n")
        # Treat equivalent current values independently of a lost conflict receipt.
        with closing(sqlite3.connect(snapshots / "4/data/tickets.sqlite")) as db, db:
            db.execute("DELETE FROM events WHERE event_id='desk-009'")
        # Complete the job before being asked to return to it.
        shutil.copyfile(snapshots / "8/data/tickets.sqlite", snapshots / "7/data/tickets.sqlite")
        (snapshots / "7/out/failed.txt").write_text("J-001\nJ-008\nJ-008\n")
        # Same state and same distinct rows, but a doubled completion marker.
        with closing(sqlite3.connect(snapshots / "8/data/tickets.sqlite")) as db, db:
            db.execute("ALTER TABLE commits RENAME TO prior")
            db.execute("CREATE TABLE commits AS SELECT * FROM prior")
            db.execute("INSERT INTO commits SELECT * FROM prior LIMIT 1")
        # Leak a late, low-revision arrival into the closed month-end report.
        history = snapshots / "11/out/history.csv"
        with history.open(encoding="utf-8", newline="") as f:
            content = list(csv.reader(f))
        content[1:] = sorted(content[1:] + [["B", "L-27", "1", "service", "open"]])
        with history.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(content)
        result = grade(run, "B", BACKEND)
        self.assertEqual(result["infrastructure_errors"], [])
        self.assertEqual(changed(result), {"CP1.migration": 4, "CP2.conflicts": 2, "CP3.atomic": 2,
                                          "CP3.detour": 5, "CP3.unique": 2, "CP5.reports": 3})

    def test_missing_legacy_entry_wrong_key_wrong_revision_and_incomplete_resume(self):
        run = self.copy_run()
        snapshots = run / "snapshots"
        (snapshots / "1/project/tickets.py").unlink()
        # Each local mutation targets one requirement, while unrelated round
        # snapshots keep the reference artifacts left by the original run.
        with closing(sqlite3.connect(snapshots / "4/data/tickets.sqlite")) as db, db:
            db.execute("UPDATE events SET ticket='17' WHERE source='B' AND ticket='0017'")
            db.execute("UPDATE events SET status='pending' WHERE event_id='desk-002'")
            db.execute("UPDATE events SET decision='accepted' WHERE event_id='desk-010'")
        with closing(sqlite3.connect(snapshots / "8/data/tickets.sqlite")) as db, db:
            db.execute("DELETE FROM commits WHERE shard='020.jsonl'")
        with closing(sqlite3.connect(snapshots / "10/data/tickets.sqlite")) as db, db:
            db.execute("DELETE FROM events WHERE event_id='return-211'")
        legacy_source = snapshots / "12/project/legacy.py"
        legacy_source.write_text(legacy_source.read_text().replace(
            'def export_csv(db, path):', 'def export_csv(db, path):\n    raise RuntimeError("retired exporter")'))
        result = grade(run, "B", BACKEND)
        diffs = changed(result)
        for key in ("CP1.legacy", "CP2.identity", "CP2.order", "CP2.dedup", "CP3.resume",
                    "CP3.unique", "CP4.withdraw", "CP4.history", "CP5.legacy"):
            with self.subTest(key=key):
                self.assertGreater(diffs.get(key, 0), 0)
        self.assertEqual(result["checks"]["CP4.history"]["earned"], 3)

    def test_append_contract_and_lossless_rerun_have_separate_partial_credit(self):
        run = self.copy_run()
        snapshots = run / "snapshots"
        # Skip subsequent legacy imports to expose a false upsert implementation.
        for path in (snapshots / "1/project/tickets.py", snapshots / "12/project/legacy.py"):
            path.write_text(path.read_text().replace(
                "def import_csv(db, path):",
                "def import_csv(db, path):\n"
                "    if db.execute(\"SELECT 1 FROM sqlite_master WHERE name='legacy'\").fetchone():\n"
                "        return"))
        # Current rows and the delivered quarantine stay correct even after loss
        # of an unmapped original row. Repeating migrate must expose that loss.
        with closing(sqlite3.connect(snapshots / "2/data/tickets.sqlite")) as db, db:
            db.execute("DELETE FROM legacy WHERE number=99")
        result = grade(run, "B", BACKEND)
        self.assertEqual(changed(result), {"CP1.legacy": 2, "CP1.migration": 3, "CP5.legacy": 2})

    def test_verified_complete_history_keeps_early_points_and_later_current_stays_strict(self):
        run = self.copy_run()
        source = (
            "\n_asof = current\n"
            "def current(conn, through=None, arrived_by=None):\n"
            "    if through is not None or arrived_by is not None:\n"
            "        return _asof(conn, through, arrived_by)\n"
            "    rows = {}\n"
            "    for cut in range(5):\n"
            "        for r in _asof(conn, cut):\n"
            "            rows[r['source'], r['ticket'], r['revision']] = r\n"
            "    return [rows[key] for key in sorted(rows)]\n")
        for folder in [run / "fault", *[run / "snapshots" / str(n) for n in (4, 6, 7, 8, 9)]]:
            path = folder / "project/views.py"
            path.write_text(path.read_text() + source)
        self.assertEqual(grade(run, "B", BACKEND)["total"], 100)
        self.assertEqual(grade_control(run, "B", BACKEND)["total"], 10)
        path = run / "snapshots/10/project/views.py"
        path.write_text(path.read_text() + source)
        self.assertEqual(changed(grade(run, "B", BACKEND)), {"CP4.withdraw": 5})

    def test_static_rebuild_passes_original_input_but_fails_perturbation(self):
        run = self.copy_run()
        snapshot = run / "snapshots/12"
        # Deliberately broken negative control: ship the known public database as code data.
        shutil.copyfile(snapshot / "data/replayed.sqlite", snapshot / "project/canned.db")
        shutil.copyfile(snapshot / "out/replay-quarantine.csv", snapshot / "project/canned.csv")
        (snapshot / "project/replay.py").write_text(
            "from pathlib import Path\nimport shutil\n"
            "def rebuild(inputs, db, quarantine):\n"
            "    shutil.copyfile(Path(__file__).with_name('canned.db'), db)\n"
            "    shutil.copyfile(Path(__file__).with_name('canned.csv'), quarantine)\n")
        result = grade(run, "B", BACKEND)
        self.assertEqual(changed(result), {"CP5.replay": 4}, result["checks"]["CP5.replay"])

    def test_no_actual_interrupt_gets_no_atomic_credit(self):
        run = self.copy_run()
        (run / "fault.json").write_text('{"status":0,"output":"done"}')
        result = grade(run, "B", BACKEND)
        self.assertEqual(changed(result), {"CP3.atomic": 5})


if __name__ == "__main__":
    unittest.main()
