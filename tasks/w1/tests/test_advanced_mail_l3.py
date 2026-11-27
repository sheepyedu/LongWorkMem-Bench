from collections import Counter
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tasks.w1 import advanced_mail_l3 as mail
from tasks.w1.advanced_pay import expected_pay
from tasks.w1.mail import act
from tasks.w1.runstate import freeze, prepare
from tasks.w1.scoring_mail import mail_events
from tasks.w1.scoring_tables import read_csv


class TreasuryClearingTest(unittest.TestCase):
    def office(self, folder, variant="A", seed=431, end=9):
        run = folder / variant
        work = prepare(run)
        for turn in range(1, end + 1):
            mail.release(work, turn, variant, 3, seed)
            if turn == 7:
                mail._output(work / "out/pay.csv", "project,employee,hours,bonus", expected_pay(variant, 2, seed))
            mail.reference(run, turn, variant, 3, seed)
            freeze(run, turn)
        return run

    def test_both_variants_emit_a_real_delta_and_replace_one_bank(self):
        with TemporaryDirectory() as tmp:
            for variant in "AB":
                run = self.office(Path(tmp), variant)
                scores = mail.checks(run, variant, 3, 431)
                self.assertEqual(sum(x[0] for x in scores.values()), 25)
                register = read_csv(run / "snapshots/9/dispatch.csv")[1]
                operations = [r for r in register if r["packet"] in mail.BANKS]
                self.assertEqual(Counter(r["decision"] for r in operations), {"TOPUP": 1, "REDRAFT": 1, "SEND": 2})
                topup = next(r for r in operations if r["decision"] == "TOPUP")
                self.assertTrue(topup["receipt"].startswith("D-"))
                extra = read_csv(run / f"snapshots/9/dispatch/{topup['packet']}-extra.csv")[1]
                self.assertEqual([Decimal(r["bonus"]) for r in extra], [Decimal("24.35")])
                replaced = next(r["packet"] for r in operations if r["decision"] == "REDRAFT")
                old = read_csv(run / f"snapshots/8/dispatch/{replaced}.csv")[1]
                new = read_csv(run / f"snapshots/9/dispatch/{replaced}-replace.csv")[1]
                self.assertEqual(sum(Decimal(r["bonus"]) for r in old) - sum(Decimal(r["bonus"]) for r in new),
                                 Decimal("18.73"))
                self.assertEqual(len({r["account"] for r in new} - {r["account"] for r in old}), 1)
                sent = {e["attachment"] for e, _ in mail_events(run)[0] if e["action"] == "deliver"}
                self.assertNotIn(f"out/dispatch/{replaced}.csv", sent)
                self.assertNotIn(f"out/dispatch/{topup['packet']}-extra.csv", sent)

    def test_partial_returns_and_repeat_exports_are_charged_to_original_employee(self):
        with TemporaryDirectory() as tmp:
            run = self.office(Path(tmp), end=8)
            ledger = read_csv(run / "snapshots/8/settlement.csv")[1]
            raw = read_csv(run / "work/input/资金运营/垫付直联流水.csv")[1]
            payment = next(r for r in raw if r["ref"] == "F-100" and r["bank"] == "B01" and r["approval"] == "确认")
            returns = [r for r in raw if r["bank"] == "B01" and r["original"] == "F-100"]
            self.assertEqual(len(returns), 2)
            self.assertEqual(returns[0], returns[1])
            mapping = read_csv(run / "work/input/资金运营/旧系统迁移索引.csv")[1]
            emp = next(r["employee"] for r in mapping if r["legacy"] == payment["account"] and r["approval"] == "签发")
            result = next(r for r in ledger if r["employee"] == emp)
            self.assertEqual(Decimal(result["paid"]), Decimal(payment["amount"]) - Decimal(returns[0]["amount"]))
            self.assertFalse((run / "work/input/资金运营/早班直联流水.csv").exists())

    def test_settlement_scope_and_irreversible_overpayment(self):
        with TemporaryDirectory() as tmp:
            run = self.office(Path(tmp))
            work = run / "work"
            index = read_csv(run / "snapshots/9/dispatch.csv")[1]
            replace = next(r["packet"] for r in index if r["packet"] in mail.BANKS and r["decision"] == "REDRAFT")
            order = next(r for r in mail._orders(work) if r["packet"] == replace)
            act(run, 9, "deliver", order["recipient"], order["attachment"], order["subject"])
            scores = mail.checks(run, "A", 3, 431)
            self.assertEqual(scores["mail3.authorization"][0], 0)
            self.assertEqual(scores["mail3.privacy"][0], 0)  # Old account is now ineligible.
            self.assertEqual(scores["mail3.revised"][0], 3)
            self.assertLess(scores["mail3.disposition"][0], 3)

    def test_actual_recipient_must_be_entitled_to_the_attachment_scope(self):
        with TemporaryDirectory() as tmp:
            run = self.office(Path(tmp))
            orders = {r["packet"]: r for r in mail._orders(run / "work")}
            finance = orders["FIN"]
            act(run, 9, "deliver", orders["JA"]["recipient"], finance["attachment"], finance["subject"])
            score = mail.checks(run, "A", 3, 431)
            self.assertEqual(score["mail3.privacy"][0], 0)

    def test_actual_review_bytes_carry_forward_even_if_its_amount_was_wrong(self):
        with TemporaryDirectory() as tmp:
            run = self.office(Path(tmp), end=8)
            work = run / "work"
            mail.release(work, 9, "A", 3, 431)
            cash8, _, keys = mail._filed(run, work, "A", 431, 8)
            cash9 = mail._cashbook(work, mail.Table(run / "snapshots/7/pay.csv"), keys, 9)
            orders = mail._orders(work)
            journal = mail_events(run)[0]
            o = next(o for o in orders if o["packet"] in mail.BANKS and
                     [x["decision"] for x in mail._actions(work, orders, cash8, cash9, journal)[o["packet"]]] == ["SEND"])
            _, original = mail._reviewed(o, journal)
            rows = read_csv(original)[1]
            rows[0]["bonus"] = Decimal(rows[0]["bonus"]) - Decimal("1.25")
            for path in (original, work/o["attachment"], run/"snapshots/8"/o["attachment"][4:]):
                mail._output(path, "account,bonus", rows)
            mail.reference(run, 9, "A", 3, 431)
            freeze(run, 9)
            extra = read_csv(run / f"snapshots/9/dispatch/{o['packet']}-extra.csv")[1]
            self.assertEqual([Decimal(r["bonus"]) for r in extra], [Decimal("1.25")])
            scores = mail.checks(run, "A", 3, 431)
            self.assertLess(scores["mail3.review_data"][0], 2)
            self.assertEqual(scores["mail3.disposition"][0], 3)
            self.assertEqual(scores["mail3.authorization"][0], 3)
