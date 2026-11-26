import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from w1 import controls
from w1.reference import solve_turn
from w1.world import release


class ControlsTests(unittest.TestCase):
    def test_seeds_and_prompt_difference(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sources"
            a = controls.make_seed(source / "A", "A")
            b = controls.make_seed(source / "B", "B")
            def files(seed):
                return {p.relative_to(seed): p.read_bytes() for p in seed.rglob("*") if p.is_file()}
            fa, fb = files(a), files(b)
            self.assertEqual(fa.keys(), fb.keys())
            self.assertEqual([p for p in fa if fa[p] != fb[p]], [Path("inbox/HR-0628.eml")])
            self.assertIn(Path("out/released.csv"), fa)
            self.assertIn(Path("out/frozen/2025-06.csv"), fa)
            self.assertNotIn(Path("out/pay.csv"), fa)
            self.assertNotIn(Path("input/hours.csv"), fa)
            with self.assertRaises(FileExistsError):
                controls.make_seed(a, "A")
            prompts = {}
            for arm in controls.ARMS:
                workspace = root / arm
                workspace.mkdir()
                prompts[arm] = controls.prepare_short(workspace, b, "B", arm)
                self.assertEqual((workspace/"inbox/HR-0628.eml").read_bytes(), fb[Path("inbox/HR-0628.eml")])
                self.assertTrue((workspace/"input/hours.csv").is_file())
                self.assertFalse((workspace/"out/pay.csv").exists())
                self.assertTrue(all(not list((workspace/k).glob("*")) for k in ("notes", "scratch")))
                self.assertEqual((workspace/"out/released.csv").read_bytes(), fb[Path("out/released.csv")])
                self.assertFalse((workspace/"input/分发清册.csv").exists())
            self.assertEqual(prompts["current"], release(root/"check", 7, "B"))
            self.assertTrue(prompts["reminder"].startswith(prompts["current"]))
            self.assertNotIn("2025-08-01", prompts["current"])
            self.assertIn("批准生效日：2025-08-01", prompts["reminder"])
            self.assertEqual(files(b), fb)

    def test_short_run_snapshot_trace_and_cp4(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = controls.make_seed(root / "seed", "A")
            runs = []
            def do_turn(run, turn, backend, gateway, session, prompt, client, *, first_session):
                self.assertEqual(turn, 7)
                self.assertTrue(first_session)
                self.assertEqual(gateway.limit, 50)
                self.assertFalse(list((run / "work/notes").iterdir()))
                self.assertFalse(list((run / "work/scratch").iterdir()))
                self.assertNotIn("2025-07-01", prompt)
                self.assertNotIn("2025-08-01", prompt)
                self.assertFalse(list((client / "desk").iterdir()))
                runs.append(session)
                solve_turn(run / "work", turn)
                (run/"trace/turn-7.jsonl").write_text("{}\n")
                return 3
            with patch.object(controls, "claude_turn", side_effect=do_turn), \
                 patch.object(controls, "isolation_check", return_value={"status":0,"output":"ok"}), \
                 patch.object(controls.platform, "platform", return_value="test"), \
                 patch.object(controls.subprocess, "check_output", return_value="dev\n"):
                run = root / "current/A"
                result = controls.play_short(run, seed, "A", "current", "seatbelt", "test-credential")
            self.assertEqual(len(runs), 1)
            self.assertEqual(result["total"], 25)
            self.assertEqual(result["max"], 25)
            self.assertEqual(set(result["items"]), {"CP4.scope","CP4.split","CP4.residual"})
            self.assertTrue(result["hr_passed"])
            self.assertEqual(list(p.name for p in (run / "snapshots").iterdir()), ["7"])
            manifest = json.loads((run/"manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["limit"], 50)
            self.assertEqual(manifest["turns"], [{"turn": 7, "upstream_calls": 3}])
            self.assertEqual(manifest["prompt_sha256"], hashlib.sha256((run/"trace/prompt-7.txt").read_bytes()).hexdigest())
            self.assertNotIn("test-credential", str(manifest))
            self.assertEqual(result, json.loads((run/"grade-cp4.json").read_text()))

    def test_empty_payroll_is_zero_of_25(self):
        with TemporaryDirectory() as tmp:
            score = controls.score_short(Path(tmp), "B")
            self.assertEqual((score["total"], score["max"], score["hr_passed"]), (0, 25, False))
