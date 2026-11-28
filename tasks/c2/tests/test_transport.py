"""Invoke the real stdio MCP entry using the exact schemas advertised to Claude."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from tasks.c2.scenario import setup
from tasks.c2.starter.calendar_io import encode


@unittest.skipUnless(os.environ.get("C2_TEST_ROOT"), "requires Docker shared directory")
class MCPContract(unittest.TestCase):
    def test_business_roundtrip(self):
        with TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as td:
            run = Path(td)
            setup(run / "work")
            (run / "trace").mkdir()
            (run / "work/out/once.ics").write_text(
                encode(
                    [dict(uid="sample", utc="2026-03-06T15:00:00Z", status="CONFIRMED")]
                )
            )
            calls = [
                ("shell", dict(command="echo ready > notes/alive; cat notes/alive")),
                ("receipts", dict(channel="A")),
                ("publish", dict(channel="A", key="once", file="out/once.ics")),
                ("receipts", dict(channel="A")),
                ("publish", dict(channel="A", key="once", file="out/once.ics")),
                ("receipts", dict(channel="B")),
                ("receipts", dict(ch="A")),
            ]
            queries = [dict(id=0, method="tools/list")]
            queries.extend(
                dict(id=i, method="tools/call", params=dict(name=n, arguments=a))
                for i, (n, a) in enumerate(calls, 1)
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tasks.c2.pilot",
                    "--serve",
                    td,
                    "4",
                    "longworkmem-calendar:1",
                ],
                input="".join(json.dumps(q) + "\n" for q in queries),
                text=True,
                capture_output=True,
                check=True,
            )
            ans = [json.loads(l)["result"] for l in proc.stdout.splitlines()]
            schema = {
                s["name"]: set(s["inputSchema"]["required"]) for s in ans[0]["tools"]
            }
            self.assertEqual(set(schema), {c[0] for c in calls})
            for (n, a), r in zip(calls[:-1], ans[1:]):
                self.assertEqual(set(a), schema[n])
                self.assertFalse(r.get("isError"))
            vals = [json.loads(r["content"][0]["text"]) for r in ans[1:-1]]
            self.assertEqual(vals[0]["output"].strip(), "ready")
            self.assertEqual(vals[1], [])
            self.assertEqual(vals[3][0]["receipt"], vals[2]["receipt"])
            self.assertTrue(vals[4]["already_received"])
            self.assertEqual(vals[5], [])
            self.assertTrue(ans[-1]["isError"])
