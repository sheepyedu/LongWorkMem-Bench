import json
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
