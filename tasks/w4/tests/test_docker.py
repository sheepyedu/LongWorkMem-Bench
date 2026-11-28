import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tasks.w1.runstate import prepare
from tasks.w4.pilot import boundary
from tasks.w4.scenario import init


@unittest.skipUnless(
    os.getenv("W4_TEST_ROOT"), "requires Docker-writable shared W4_TEST_ROOT"
)
class DockerTest(unittest.TestCase):
    def test_stdio_and_frozen_attachment(self):
        with TemporaryDirectory(dir=os.environ["W4_TEST_ROOT"]) as tmp:
            run = Path(tmp) / "check"
            work = prepare(run)
            init(work)
            img = subprocess.check_output(
                [
                    "docker",
                    "image",
                    "inspect",
                    "longworkmem-release:1",
                    "-f",
                    "{{.Id}}",
                ],
                text=True,
            ).strip()
            boundary(run, img)

            def rpc(t, m, **args):
                msg = {"id": 1, "method": m, "params": args}
                raw = subprocess.check_output(
                    [sys.executable, "-m", "tasks.w4.office", str(run), str(t), img],
                    input=json.dumps(msg) + "\n",
                    text=True,
                )
                return json.loads(raw)["result"]

            def call(t, name, **args):
                reply = rpc(t, "tools/call", name=name, arguments=args)
                self.assertFalse(reply.get("isError"), reply)
                return json.loads(reply["content"][0]["text"])

            self.assertEqual(
                {s["name"] for s in rpc(1, "tools/list")["tools"]},
                {"shell", "deliver", "draft", "receipt_query"},
            )
            self.assertEqual(
                call(10, "shell", command="echo old > out/service.md")["status"], 0
            )
            args = dict(
                subject="U01",
                recipient="hz.new@office.test",
                attachment="out/service.md",
            )
            call(10, "draft", **args)
            ref = call(10, "deliver", **args)["receipt"]
            call(11, "shell", command="echo new > out/service.md")
            got = call(12, "receipt_query", case="U01", as_of="10", receipt=ref)
            self.assertEqual(
                [(e["status"], e["payload"]) for e in got], [("待确认", "old\n")]
            )
            self.assertTrue(
                rpc(
                    10,
                    "tools/call",
                    name="deliver",
                    arguments=dict(args, attachment="../manifest.json"),
                ).get("isError")
            )
