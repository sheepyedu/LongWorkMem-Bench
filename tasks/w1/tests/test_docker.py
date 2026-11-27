"""Opt-in integration from the same MCP contract used by Claude Code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tasks.w1.pilot import isolation_check
from tasks.w1.runstate import freeze, prepare


@unittest.skipUnless(os.environ.get("W1_TEST_DOCKER") == "1", "set W1_TEST_DOCKER=1 with a built office image")
class DockerOfficeTest(unittest.TestCase):
    def test_isolated_office_and_actual_formula_engine(self):
        with tempfile.TemporaryDirectory(dir=os.getenv("W1_TEST_ROOT")) as tmp:
            run = Path(tmp)/"company"
            work = prepare(run)
            isolation_check(work, "docker")
            command = """set -eu
mkdir -p scratch/recalculated
python3 - <<'END'
from openpyxl import Workbook
book=Workbook()
book.active['A1']=4
book.active['B1']='=A1+5'
book.save('out/example.xlsx')
END
soffice --headless --convert-to xlsx --outdir scratch/recalculated out/example.xlsx
python3 - <<'END'
from openpyxl import load_workbook
v=load_workbook('scratch/recalculated/example.xlsx',data_only=True).active['B1'].value
assert v==9,v
print('recalculated value 9')
END"""
            def call(n, name, args):
                return {"jsonrpc":"2.0","id":n,"method":"tools/call","params":{"name":name,"arguments":args}}
            args={"recipient":"finance@office.test","attachment":"out/example.xlsx","subject":"内部校验"}
            requests=[call(1,"shell",{"command":command}),call(2,"draft",args),call(3,"deliver",args)]
            completed=subprocess.run([sys.executable,"-m","tasks.w1.office",str(run),"8","docker"],
                input="".join(json.dumps(r)+"\n" for r in requests),text=True,capture_output=True,timeout=120,check=True)
            responses=[json.loads(line)["result"] for line in completed.stdout.splitlines()]
            values=[json.loads(v["content"][0]["text"]) for v in responses]
            self.assertEqual(values[0]["status"],0,values[0])
            self.assertIn("recalculated value 9",values[0]["output"])
            freeze(run,8)
            for value, kind in zip(values[1:], ("D-", "M-")):
                receipt = value["receipt"]
                self.assertTrue(receipt.startswith(kind))
                self.assertEqual((run/"mail/8"/receipt/"payload").read_bytes(),
                                 (run/"snapshots/8/example.xlsx").read_bytes())
