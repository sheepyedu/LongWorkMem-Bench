from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_mail_l4 as mail
from w1.advanced_ledger_score import expected
from w1.advanced_pay_l4 import expected_pay
from w1.mail import act
from w1.runstate import freeze, prepare
from w1.scoring_mail import mail_events
from w1.scoring_tables import read_csv


class InquiryTest(unittest.TestCase):
    def office(self, root, *, variant="A", seed=431, skip_first=False, end=9):
        run = root / variant
        work = prepare(run)
        for turn in range(1, end + 1):
            mail.release(work, turn, variant, 4, seed)
            if turn == 7:
                mail.treasury._output(work / "out/pay.csv", "project,employee,hours,bonus", expected_pay(variant, 4, seed))
            if not (turn == 2 and skip_first):
                mail.reference(run, turn, variant, 4, seed)
            freeze(run, turn)
        return run

    def test_actual_supplier_cases_and_all_three_send_windows_for_both_worlds(self):
        seed = 431
        real = {tuple(str(r[k]) for k in ("site", "id", "po", "line"))
                for r in expected(2, seed)[2][1] if r["source"] == "invoice"}
        cases = mail._requests(seed)[0]
        self.assertTrue(all(tuple(r.values()) in real for rows in cases.values() for r in rows))
        with TemporaryDirectory() as tmp:
            for variant in "AB":
                run = self.office(Path(tmp), variant=variant, seed=seed)
                results = mail.checks(run, variant, 4, seed)
                self.assertEqual(sum(r[0] for r in results.values()), 25, results)
                events, _ = mail_events(run)
                self.assertEqual([sum(e["turn"] == t and e["action"] == "deliver" for e,_ in events)
                                  for t in mail.EARLY], [2, 2, 2])
                index = read_csv(run / "snapshots/9/verify_index.csv")[1]
                prior = {r["desk"]:r["receipt"] for r in index if r["stage"] == "首询"}
                self.assertTrue(all(r["prior"] == prior[r["desk"]] for r in index if r["stage"] == "续核"))
                first = {r["desk"]:r["recipient"] for r in index if r["stage"] == "首询"}
                self.assertEqual(sum(r["recipient"] != first[r["desk"]] for r in index if r["stage"] == "续核"), 1)

    def test_missing_first_window_still_allows_recovery_using_blank_reference(self):
        with TemporaryDirectory() as tmp:
            run = self.office(Path(tmp), skip_first=True)
            results = mail.checks(run, "A", 4, 431)
            self.assertEqual(results["mail4.r2_route"][0], 0)
            for key in ("r5_content", "r5_record", "r6_record", "authorization", "privacy"):
                self.assertEqual(results["mail4." + key][:2], (results["mail4." + key][1],) * 2)

    def test_actual_early_scope_and_forged_thread_are_independently_detected(self):
        with TemporaryDirectory() as tmp:
            run = self.office(Path(tmp))
            journal, _ = mail_events(run)
            e, p = next((e,p) for e,p in journal if e["turn"] == 6)
            rows = read_csv(p)[1]
            for row in rows:
                row["employee"] = "E07"
            mail.treasury._output(p, "bank,ref,original,amount,employee", rows)
            early = run / "snapshots/5/verify_index.csv"
            rows = read_csv(early)[1]
            next(r for r in rows if r["stage"] == "续核")["prior"] = "M-fiction"
            mail.treasury._output(early, mail.INDEX, rows)
            results = mail.checks(run, "A", 4, 431)
            self.assertEqual(results["mail4.r6_content"][0], 1)
            self.assertEqual(results["mail4.r5_record"][0], .5)
            self.assertEqual(results["mail4.privacy"][0], 0)
            self.assertEqual(results["mail4.authorization"][0], 0)
            self.assertEqual(results["mail4.disposition"][0], 1.5)

    def test_case_sent_late_or_twice_cannot_satisfy_window(self):
        with TemporaryDirectory() as tmp:
            run = self.office(Path(tmp))
            event, _ = next((e,p) for e,p in mail_events(run)[0] if e["turn"] == 2)
            for turn in (2, 4):
                act(run, turn, event["action"], event["recipient"], event["attachment"], event["subject"])
            result = mail.checks(run, "A", 4, 431)
            self.assertEqual(result["mail4.r2_route"][0], .5)
            self.assertEqual(result["mail4.r5_content"][0], 1)
            # All duplicates went to the AP desk authorized to see this exact site/period.
            self.assertEqual(result["mail4.privacy"][0], 1)
            self.assertEqual(result["mail4.authorization"][0], 0)
