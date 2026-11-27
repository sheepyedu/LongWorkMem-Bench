from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_pay_l4 as pay
from w1 import advanced_pay_checks as payroll
from w1.runstate import freeze, prepare


class QuarterlyPayroll(unittest.TestCase):
    def test_quarter_threshold_increment_and_joint_signature(self):
        key = ("甲", "E01")
        for old, new, expected in [(35,5,5),(38,6,8),(45,4,6)]:
            self.assertEqual(payroll.settlement_hours({key:D(new)}, {key:D(old)})[key], D(expected))
        proposals = [
            dict(site="东厂",ticket="T",revision=str(r),destination="乙",percent="50",decision=s)
            for r,s in [(1,"改派"),(2,"撤回"),(3,"改派")]]
        stamps = [dict(site="东厂",ticket="T",revision=str(rev),authority=who,decision="签发",signed=day)
                  for rev,who,day in [(1,"人事","2025-08-02 16:30"),(1,"财务","2025-08-03 17:30"),
                                      (2,"人事","2025-08-03 17:00"),(2,"财务","2025-08-03 18:01"),
                                      (3,"财务","2025-08-03 16:35")]]
        self.assertEqual(pay.resolve_orders(proposals,stamps)[("东厂","T")]["revision"],"1")
        stamps[-2]["signed"]="2025-08-03 18:00"
        self.assertEqual(pay.resolve_orders(proposals,stamps),{})

    def test_reference_and_missing_adjustment_evidence(self):
        with TemporaryDirectory() as temp:
            run=Path(temp)/"run"
            work=prepare(run)
            for turn in range(1,10):
                pay.release(work,turn,"A",4,73)
                pay.reference(run,turn,"A",4,73)
                freeze(run,turn)
            result=pay.checks(run,"A",4,73)
            self.assertEqual(sum(v[1] for v in result.values()),35)
            self.assertEqual(sum(v[0] for v in result.values()),35,result)
            from w1.advanced_pay_l3 import expected_pay
            self.assertNotEqual(pay.expected_pay("A",4,73),expected_pay("A",3,73))
            self.assertNotEqual(pay.expected_pay("A",4,73),pay.expected_pay("B",4,73))
            (run/"snapshots/7/time_transfers.csv").unlink()
            self.assertEqual(pay.dispatch_check(run,pay.pristine("A",73)["orders"])[0],0)

    def test_split_pending_partial_full_and_released_after_assignment(self):
        with TemporaryDirectory() as temp:
            work = prepare(Path(temp) / "company")
            for turn in range(1, 7):
                pay.release(work, turn, "A", 4, 45)
            def ticket(key, project, units, decision="已核"):
                return dict(site="西厂", ticket=key, revision="1", employee="E07", worked="2025-07-23",
                            project=project, unit="MIN", units=units, decision=decision, posted="2025-08-03 18:00")
            rows = [ticket("A", "待查", "240"), ticket("B","待查","120"), ticket("C","共享","300"),
                    ticket("D","甲","60","作废"), ticket("E","甲","60")]
            orders = {("西厂", key):dict(destination=dest, percent=percent)
                      for key, dest, percent in [("A","甲",25),("B","乙",100),("C","乙",50),("D","乙",100)]}
            _, hours, _, pending = payroll.reconstruct(work, 2, rows=rows, orders=orders)
            # E07's shared duty on July 23 is unapproved project 丙. The 50% transfer is payable.
            self.assertEqual(hours, {("甲","E07"):D("2"),("乙","E07"):D("4.5")})
            self.assertEqual(pending, {("西厂","A")})
