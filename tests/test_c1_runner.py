import json
import os
import platform
from pathlib import Path
import tempfile
import unittest

from c1.review import audit
from c1.runstate import freeze


class CheckoutTests(unittest.TestCase):
    def test_snapshots_preserve_deletions_modes_and_internal_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            work.mkdir()
            entry = work / "service"
            entry.write_text("old")
            entry.chmod(0o755)
            (work / "inside").symlink_to("service")
            (work / "outside").symlink_to("../private")
            self.assertEqual(freeze(work, root / "first"), ["outside"])
            entry.unlink()
            (work / "inside").unlink()
            self.assertEqual(freeze(work, root / "second"), ["outside"])
            self.assertEqual((root / "first/inside").read_text(), "old")
            self.assertTrue((root / "first/service").stat().st_mode & 0o100)
            self.assertFalse((root / "second/service").exists())
            self.assertFalse((root / "first/outside").is_symlink())
            with self.assertRaises(FileExistsError):
                freeze(work, root / "first")

    def test_audit_reports_missing_receipt_and_invalid_cli_row(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "trace").mkdir()
            (run / "manifest.json").write_text(json.dumps(dict(status="complete", session="s",
                turns=[dict(turn=1, upstream_calls=1)], model="test")))
            (run / "trace/turn-1.jsonl").write_text("not-json\n")
            summary = audit(run)
            self.assertTrue(any("manifest has 1 attempts" in issue for issue in summary["flags"]))
            self.assertTrue(any("turn-1.jsonl:1" in issue for issue in summary["flags"]))

    @unittest.skipUnless(platform.system() == "Darwin" or os.getenv("C1_TEST_DOCKER") == "1",
                         "requires an isolated code backend")
    def test_untouched_starter_only_earns_legacy_compatibility_and_preservation(self):
        from c1 import sandbox, world
        from c1.grade import grade
        backend = "docker" if os.getenv("C1_TEST_DOCKER") == "1" else "seatbelt"
        with tempfile.TemporaryDirectory(dir=os.getenv("C1_TEST_ROOT")) as directory:
            run = Path(directory)
            for turn in range(1, 13):
                work = run / "work"
                world.release(work, turn, "B")
                if turn == 6:
                    stopped = sandbox.shell(work, world.batch_command(True), backend)
                    self.assertNotEqual(stopped["status"], 86)
                    (run / "fault.json").write_text(json.dumps(stopped))
                    freeze(work, run / "fault")
                freeze(work, run / "snapshots" / str(turn))
            result = grade(run, "B", backend)
            earned = {key: item["earned"] for key, item in result["checks"].items() if item["earned"]}
            self.assertTrue(result["valid"], result["infrastructure_errors"])
            self.assertEqual(earned, {"CP1.legacy": 5, "CP1.migration": 2, "CP5.legacy": 5})

    def test_cli_unavailable_tool_is_a_verifiable_client_receipt(self):
        from c1.review import result_value
        rejection = '<tool_use_error>Error: No such tool available: workshop__shell</tool_use_error>'
        self.assertEqual(result_value(rejection), {'client_error': rejection})
        with self.assertRaises(ValueError):
            result_value('unexpected unstructured output')
