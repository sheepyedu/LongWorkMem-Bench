from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_memory as mem


class MandateTests(unittest.TestCase):
    def test_partial_withdrawal_expiry_and_transfer(self):
        rules = mem.mandate(431)
        row = dict(office="南港", case="X", kind=rules["kind"], employee="E07", project="共享",
                   worked="2025-07-16", vendor="常规", amount="1.00")
        active = mem.decision(row, "2025-08-04", rules, "2025-07-16")
        historical = mem.decision(row, "2025-08-04", rules, "2025-08-16")
        self.assertEqual((active["project"], active["authority"]), ("乙", rules["temporary"]))
        self.assertEqual(historical["project"], "甲")
        restored = mem.decision(row, "2025-08-05", rules, "2025-07-16")
        self.assertEqual(restored["authority"], rules["base_id"])
        withdrawn = mem.decision(dict(row,office="江东"), "2025-08-04", rules, "2025-07-16")
        self.assertEqual(withdrawn["authority"], rules["base_id"])
        stop = mem.decision(dict(row,vendor=rules["vendor"]), "2025-08-04", rules, "2025-07-16")
        self.assertEqual((stop["decision"], stop["target"]), ("HOLD", 0))

    def test_delta_uses_filed_amount_and_duplicate_has_no_unique_receipt(self):
        from w1.world import _csv
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/"posted.csv"
            _csv(p,"office,case,target",[("南港","K03","37.000"),("江东","K03",10),("江东","K03",20)])
            self.assertEqual(mem.filed_amounts(p), {("南港","K03"):37})
