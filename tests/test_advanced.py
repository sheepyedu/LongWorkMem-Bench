from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from w1.advanced import grade, public_digest, release, run_reference
from w1.runstate import ROUNDS


class AdvancedOfficeTest(unittest.TestCase):
    def test_every_release_is_repeatable_and_only_hr_differs_in_pair(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for level in (1, 2, 3, 4, 5, 6):
                left, right, repeated = (root / f"{level}-{tag}" for tag in ("A", "B", "again"))
                for turn in ROUNDS:
                    prompt = release(left, turn, "A", level, 431)
                    self.assertEqual(prompt, release(right, turn, "B", level, 431))
                    self.assertEqual(prompt, release(repeated, turn, "A", level, 431))
                    self.assertEqual(public_digest(left, prompt), public_digest(repeated, prompt))
                    a = {p.relative_to(left): p.read_bytes() for p in left.rglob("*") if p.is_file()}
                    b = {p.relative_to(right): p.read_bytes() for p in right.rglob("*") if p.is_file()}
                    self.assertEqual(a.keys(), b.keys())
                    differences = {p for p in a if a[p] != b[p]}
                    self.assertEqual(differences, {Path("inbox/HR-0628.eml")} if turn >= 2 else set())

    def test_windows_add_only_the_public_batch_notice(self):
        from w1.erp_window import notice
        with TemporaryDirectory() as tmp:
            plain, window = Path(tmp) / "plain", Path(tmp) / "window"
            for turn in ROUNDS:
                original = release(plain, turn, "A", 4, 431)
                timed = release(window, turn, "A", 5, 431)
                self.assertEqual(timed, original + notice(turn))
                self.assertEqual(public_digest(window, original), public_digest(plain, original))

    def test_reference_scores_and_incomplete_run_is_not_a_model_grade(self):
        with TemporaryDirectory() as tmp:
            for level, variant in ((1, "A"), (2, "B"), (3, "A"), (3, "B"), (4, "A"), (4, "B"), (5, "A"), (6, "B")):
                run = Path(tmp) / f"{level}-{variant}"
                run_reference(run, variant, level, 431)
                result = grade(run, variant)
                self.assertEqual(result["total"], 100, result["items"])
                manifest = run / "manifest.json"
                data = json.loads(manifest.read_bytes())
                data["status"] = "error"
                manifest.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "completed"):
                    grade(run)
