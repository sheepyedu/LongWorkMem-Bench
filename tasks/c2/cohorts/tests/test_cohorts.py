import json
import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from .. import runner
from ..grade import fields_by_key, grade
from ..scenario import CHANNELS
from .controls import drive


class Scoring(unittest.TestCase):
    def test_bad_field_does_not_erase_sibling(self):
        row = dict(account="B", received="bad", pending=False)
        self.assertEqual(
            fields_by_key([row], ["account"], ["received", "pending"])[("B",)],
            ["missing", False],
        )
        self.assertEqual(
            fields_by_key([row, row], ["account"], ["pending"])[("B",)], ["missing"]
        )
        row.update(received=None)
        self.assertEqual(
            fields_by_key([row], ["account"], ["received"])[("B",)], [None]
        )

    def test_old_run_cannot_receive_new_full_score(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path / "manifest.json").write_text(
                json.dumps(dict(protocol="calendar-evolution-v1"))
            )
            with self.assertRaisesRegex(ValueError, "complete customer migration"):
                grade(path)


@unittest.skipUnless(os.getenv("C2_TEST_ROOT"), "requires Docker shared scratch")
class Integration(unittest.TestCase):
    def test_full_release_and_local_deductions(self):
        with tempfile.TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as d:
            path = Path(d)
            drive(path)
            from tasks.c2.evolution.grade import grade as dispatch_grade

            gold = dispatch_grade(path)
            items = gold["items"]
            self.assertEqual(gold["total"], 100)
            self.assertEqual(sum(Fraction(i["weight"]) for i in items.values()), 100)
            self.assertTrue(all(0 < Fraction(i["weight"]) <= 1 for i in items.values()))
            deliveries = json.loads((path / "receipts/9.json").read_text())
            for a in CHANNELS:
                self.assertEqual(
                    [b["key"] for b in deliveries[a] if b["turn"] == 9],
                    ["handover-D-Q29"] if a == "D" else [],
                )
            # Change a single field in one filed inquiry. Program and receipt evidence stay intact.
            file = path / "snapshots/10/out/inquiry.json"
            rows = json.loads(file.read_text())
            rows[0]["pending"] = "false"
            file.write_text(json.dumps(rows))
            new = grade(path)
            lost = [k for k, i in new["items"].items() if not i["passed"]]
            self.assertEqual(lost, ["10/historical-file/A/Q29/2026-03-09/4/pending"])

    def test_real_mcp_and_restore_boundaries(self):
        with tempfile.TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as tmp:
            p = Path(tmp)
            runner.setup(p / "work")
            (p / "trace").mkdir()
            for t in range(1, 9):
                runner.release(p, t)
            (p / "work/data/post-incident.txt").write_text("discard")
            runner.release(p, 9)
            self.assertFalse((p / "work/data/post-incident.txt").exists())

            def call(tool, args, i):
                return dict(
                    id=i, method="tools/call", params=dict(name=tool, arguments=args)
                )

            msgs = [
                dict(id=0, method="tools/list"),
                call("receipts", dict(channel="C"), 1),
                call("receipts", dict(channel="D"), 2),
                call(
                    "shell",
                    dict(
                        command="test ! -e ../receipts && test -f input/repair-disk/receipt-cache.json && test ! -e project/service.py && test ! -e /var/run/docker.sock && ! touch input/no-write 2>/dev/null && echo isolated"
                    ),
                    3,
                ),
            ]
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    runner.SERVER_MODULE,
                    "--serve",
                    tmp,
                    "9",
                    "longworkmem-calendar:1",
                ],
                input="".join(json.dumps(m) + "\n" for m in msgs),
                text=True,
                capture_output=True,
                check=True,
            )
            data = [json.loads(l)["result"] for l in proc.stdout.splitlines()]
            self.assertEqual(
                {t["name"] for t in data[0]["tools"]}, {"shell", "receipts", "publish"}
            )
            values = [json.loads(x["content"][0]["text"]) for x in data[1:]]
            self.assertEqual(values[0][0]["key"], "handover-C-Q29")
            self.assertEqual(values[1], [])
            self.assertEqual(values[2]["output"].strip(), "isolated")
