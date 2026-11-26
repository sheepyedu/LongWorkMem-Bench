import json
from pathlib import Path
import platform
import tempfile
import unittest

from w1.mail import act
from w1.office import shell
from w1.runstate import freeze, prepare


class OfficeTest(unittest.TestCase):
    def test_delivery_and_checkpoint_capture_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            run = Path(root) / "run"
            work = prepare(run)
            file = work / "out/a.csv"
            file.write_text("first")
            mid = act(run, 4, "deliver", "finance@office.test", "out/a.csv", "六月")
            freeze(run, 4)
            file.write_text("replaced")
            self.assertEqual((run / "snapshots/4/a.csv").read_text(), "first")
            self.assertEqual((run / "mail/4" / mid / "payload").read_text(), "first")
            (work / "out/bad").symlink_to(run / "mail/4" / mid / "payload")
            with self.assertRaises(ValueError):
                act(run, 4, "deliver", "finance@office.test", "out/bad", "file")
            freeze(run, 5)
            self.assertFalse((run / "snapshots/5/bad").exists())

    @unittest.skipUnless(platform.system() == "Darwin", "macOS profile")
    def test_model_tool_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            run = Path(root) / "run"
            work = prepare(run)
            (run / "private-marker").write_text("blind")
            (work / "input/notice").write_text("public")
            probe = """python3 - <<'END'
import pathlib, socket
from openpyxl import Workbook
p = pathlib.Path
assert p('input/notice').read_text() == 'public'
Workbook().save('out/book.xlsx')
for action in [lambda: p('../private-marker').read_text(), lambda: p('input/notice').write_text('bad'), lambda: socket.socket().connect(('127.0.0.1', 80))]:
    try:
        action()
    except PermissionError:
        continue
    raise SystemExit('office boundary failed')
print('access-checked')
END"""
            result = shell(work, probe, "seatbelt")
            self.assertEqual(result["status"], 0, result)
            self.assertIn("access-checked", result["output"])
