from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from w1.pilot import office_runtime


class RuntimeTests(unittest.TestCase):
    def test_office_modules_pinned_once_outside_work_without_evaluation(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            code = office_runtime(run)
            files = {p.name for p in (code/"w1").glob("*.py")}
            self.assertEqual(files, {"__init__.py","office.py","mail.py","erp_window.py","office_protocol.py","runstate.py"})
            self.assertFalse(code.is_relative_to(run/"work"))
            original = (code/"w1/office.py").read_bytes()
            self.assertEqual(office_runtime(run),code)
            self.assertEqual((code/"w1/office.py").read_bytes(),original)
