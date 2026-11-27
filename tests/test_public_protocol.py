"""Public fixture identity and regression tests for the published scoring contract."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tasks.protocol import PUBLIC_SEED, PUBLIC_VARIANT
from tasks.c1 import calibrate, pilot
from tasks.c1.settlement_grade import row_difference
from tasks.s1.circuit import Circuit, REGISTER_PHASE
from tasks.w1 import advanced


def material_hashes():
    with TemporaryDirectory() as tmp:
        office, desk = Path(tmp) / "office", Path(tmp) / "desk"
        w1, c1 = [], []
        for turn in range(1, 10):
            prompt = advanced.release(office, turn, PUBLIC_VARIANT, 8, PUBLIC_SEED, erp_window=False)
            w1.append(advanced.public_digest(office, prompt))
        for turn in range(1, 8):
            prompt = pilot.release_turn(desk, turn, PUBLIC_VARIANT, PUBLIC_SEED, 3, None, True)
            h = sha256(prompt.encode() + b"\0")
            for p in sorted((desk / "input").rglob("*")):
                if p.is_file():
                    h.update(p.relative_to(desk).as_posix().encode() + b"\0" + sha256(p.read_bytes()).digest())
            c1.append(h.hexdigest())
    c = Circuit(PUBLIC_SEED, PUBLIC_VARIANT, 10, 2, 2, version=3)
    forms = [c.rules] + [c.prompt(i, "handover", "") for i in range(1, 81)]
    return {"w1":w1, "c1":c1, "s1":[sha256(form.encode()).hexdigest() for form in forms]}


class PublicProtocolTest(unittest.TestCase):
    def test_published_materials(self):
        fixture = Path(__file__).with_name("public-v1-materials.json")
        self.assertEqual(material_hashes(), json.loads(fixture.read_text()))

    def test_c1_default_one_public_instance_no_cap_or_early_dispatch(self):
        with patch("sys.argv", ["calibrate", "dest"]), patch.dict("os.environ", C1_UPSTREAM_KEY="fixture"), patch.object(calibrate, "run_session") as launch:
            calibrate.main()
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[1], "A")
        self.assertEqual(launch.call_args.kwargs["seed"], PUBLIC_SEED)
        self.assertIsNone(launch.call_args.kwargs["window"])
        self.assertIsNone(launch.call_args.kwargs["limit"])
        self.assertEqual(row_difference([[1],[2],[2]], [[1],[2]]), dict(expected_rows=2,missing=0,extra=1,array_present=True))
        self.assertFalse(row_difference(None, [])["array_present"])

    def test_typed_registration_and_old_parser(self):
        c = Circuit(PUBLIC_SEED, "A", 10, 2, 2, version=3)
        desk, stage = c.schedule[0]
        teams = c.register_teams(desk, stage)
        rows = {t:["F4","43","桃","北"] for t in teams}
        wrapped = {t:{REGISTER_PHASE[stage]:v} for t,v in rows.items()}
        self.assertEqual(c.submission(1, {"register": rows}), c.submission(1, {"register":wrapped}))
        for bad in ({}, {t:{"错误赛段":v} for t,v in rows.items()}, {t:v[:2] for t,v in rows.items()}):
            with self.assertRaises(ValueError):
                c.submission(1, {"register":bad})
        old = Circuit(PUBLIC_SEED, "A", 10, 2, 2, version=2)
        self.assertFalse(old.submission(1, {"register":wrapped})["register"])

    def test_experiment_stop_records_progress_without_a_benchmark_score(self):
        from tasks.c1.settlement_grade import grade
        from tasks.protocol import PROTOCOL
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "manifest.json").write_text(json.dumps(dict(status="budget_exhausted",protocol=PROTOCOL,turns=[{}]*4)))
            with patch("tasks.c1.settlement_grade.grade_snapshot", return_value=dict(total=14,valid=True,observed_points=14)):
                result = grade(run)
            self.assertIsNone(result["total"])
            self.assertEqual(result["unreached_turns"], [6,7])
            self.assertEqual(result["observed_points"], 14)
