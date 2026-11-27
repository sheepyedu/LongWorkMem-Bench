from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_pay as pay
from w1.runstate import prepare, freeze


class AdvancedPayTests(unittest.TestCase):
    def test_timed_release_and_counterfactual(self):
        with TemporaryDirectory() as tmp:
            worlds = [prepare(Path(tmp) / variant) for variant in "AB"]
            for turn in range(1, 8):
                prompts = [pay.release(work, turn, variant, 2, 19) for work, variant in zip(worlds, "AB")]
                self.assertEqual(*prompts)
                if turn < 7:
                    self.assertFalse((worlds[0] / "input/工时中心/主账.csv").exists())
            a, b = [{p.relative_to(w): p.read_bytes() for p in w.rglob("*") if p.is_file()} for w in worlds]
            self.assertEqual(set(a), set(b))
            self.assertEqual([k for k in a if a[k] != b[k]], [Path("inbox/HR-0628.eml")])
            payments = [pay.expected_pay(v, 2, 19) for v in "AB"]
            self.assertEqual(*[sum(r["bonus"] for r in rows) for rows in payments])
            hours = [{r["project"]: r["hours"] for r in rows if r["employee"] == "E07"} for rows in payments]
            self.assertLess(hours[0]["甲"], hours[1]["甲"])
            self.assertGreater(hours[0]["乙"], hours[1]["乙"])
            self.assertNotEqual(payments[0], pay.expected_pay("A", 2, 23))

    def test_full_reference_and_missing_outputs(self):
        with TemporaryDirectory() as tmp:
            for level, variant in [(1, "B"), (2, "A")]:
                run = Path(tmp) / str(level)
                work = prepare(run)
                self.assertEqual(sum(x[0] for x in pay.checks(run, variant, level, 13).values()), 0)
                for turn in range(1, 10):
                    pay.release(work, turn, variant, level, 13)
                    pay.reference(run, turn, variant, level, 13)
                    freeze(run, turn)
                scores = pay.checks(run, variant, level, 13)
                self.assertEqual(sum(s[1] for s in scores.values()), 35)
                self.assertEqual(sum(s[0] for s in scores.values()), 35, scores)

    def test_tail_can_trigger_a_contract_limit_even_below_the_nominal_share(self):
        from w1.advanced_pay_checks import awards
        team = {("甲", f"E0{i}"): Decimal("1") for i in range(1, 5)}
        result = awards(team, {"甲": Decimal("1.03")}, {("甲", "E01"): Decimal(".26")})
        self.assertEqual(list(result[k] for k in sorted(team)),
                         [Decimal(".26"), Decimal(".27"), Decimal(".25"), Decimal(".25")])
        self.assertEqual(sum(result.values()), Decimal("1.03"))

    def test_cutoff_cancellation_cross_site_id_and_date_scoped_duty(self):
        from w1.advanced_pay_checks import reconstruct
        from w1.world import _csv
        with TemporaryDirectory() as tmp:
            work = prepare(Path(tmp) / "company")
            for turn in (1, 2, 4, 6, 7):
                pay.release(work, turn, "A", 2, 45)
            def ticket(site, key, rev, day, project, units, decision="已核", posted="2025-08-03 18:00"):
                return (site, key, rev, "E07", f"2025-07-{day:02}", project, units, "MIN", decision, posted)
            primary = [ticket("东厂","T",1,15,"共享",60), ticket("西厂","T",1,16,"共享",120),
                       ticket("东厂","U",1,21,"共享",240), ticket("东厂","V",1,21,"甲",45),
                       ticket("东厂","W",1,25,"待查",60), ticket("西厂","W",1,26,"待查",45),
                       ticket("西厂","X",1,13,"甲",60)]
            revisions = [primary[0], ticket("东厂","T",2,15,"共享",105),
                         ticket("东厂","T",3,15,"共享",300,"待核"), ticket("西厂","X",2,13,"甲",60,"作废"),
                         ticket("西厂","T",2,16,"共享",60,"作废","2025-08-03 18:01")]
            _csv(work / "input/工时中心/主账.csv", pay.TIME_FIELDS, primary)
            _csv(work / "input/工时中心/补正.csv", pay.TIME_FIELDS, revisions)
            _, hours, _, pending = reconstruct(work, 2)
            self.assertEqual(hours, {("甲","E07"): Decimal("2.5"), ("乙","E07"): Decimal("2")})
            self.assertEqual(pending, {("东厂","W"),("西厂","W")})

    def test_calc_process_failure_cannot_become_a_payroll_score(self):
        import subprocess
        from unittest.mock import patch
        from w1.advanced_pay_checks import pristine, recalc, workbook
        from w1.scoring_tables import Table

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            oracle = pristine("A", 2, 13)
            workbook(root / "bonus.xlsx", oracle["pools"], oracle["hours"], oracle["caps"])
            for returncode in (0, 1):
                # Even exit 0 without any converted cases leaves no grading evidence.
                completed = subprocess.CompletedProcess([], returncode)
                with self.subTest(returncode=returncode), patch(
                    "w1.advanced_pay_checks.subprocess.run", return_value=completed
                ), self.assertRaises(RuntimeError):
                    recalc(root / "bonus.xlsx", Table(root / "pay.csv"), oracle)

            with patch(
                "w1.advanced_pay_checks.subprocess.run",
                side_effect=subprocess.TimeoutExpired("soffice", 100),
            ), self.assertRaises(RuntimeError):
                recalc(root / "bonus.xlsx", Table(root / "pay.csv"), oracle)

    def test_static_correct_workbook_has_no_dynamic_credit(self):
        from openpyxl import load_workbook
        from w1.advanced_pay_checks import pristine, recalc, solve
        from w1.scoring_tables import Table
        with TemporaryDirectory() as tmp:
            work = prepare(Path(tmp) / "company")
            for turn in (1, 2, 4, 6, 7):
                pay.release(work, turn, "A", 2, 13)
            solve(work, 7, 2)
            oracle = pristine("A", 2, 13)
            path = work / "out/bonus.xlsx"
            book = load_workbook(path)
            for i, row in enumerate(oracle["pay"], 2):
                book["Pay"].cell(i, 4).value = row["bonus"]
            book.save(path)
            book.close()
            checks = recalc(path, Table(work / "out/pay.csv"), oracle)
            self.assertEqual([ratio for ratio, _ in checks], [1, 0, 0])

    def test_penny_error_in_pool_does_not_hide_valid_formulas(self):
        from w1.advanced_pay_checks import awards, pay_rows, pristine, recalc, workbook
        from w1.reference import PAY, write_csv
        from w1.scoring_tables import Table
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            oracle = pristine("A", 2, 13)
            submitted_pools = oracle["pools"].copy()
            submitted_pools["甲"] += Decimal(".01")
            hours, caps = oracle["hours"], oracle["caps"]
            workbook(root / "bonus.xlsx", submitted_pools, hours, caps)
            write_csv(root / "pay.csv", PAY, pay_rows(hours, awards(hours, submitted_pools, caps)))
            checks = recalc(root / "bonus.xlsx", Table(root / "pay.csv"), oracle)
            self.assertEqual([ratio for ratio, _ in checks], [0, 1, 1], checks)

    def test_static_one_cent_pools_cannot_get_credit_for_unchanged_outputs(self):
        from openpyxl import load_workbook
        from w1.advanced_pay_checks import awards, pay_rows, pristine, recalc, workbook
        from w1.reference import PAY, write_csv
        from w1.scoring_tables import Table
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            oracle = pristine("A", 1, 17)
            hours, caps = oracle["hours"], oracle["caps"]
            pools = dict.fromkeys(oracle["pools"], Decimal(".01"))
            nominal = awards(hours, pools, caps)
            path = root / "bonus.xlsx"
            workbook(path, pools, hours, caps)
            book = load_workbook(path)
            for ix, key in enumerate(sorted(hours), 2):
                book["Pay"].cell(ix, 4, nominal[key])
            book.save(path)
            book.close()
            write_csv(root / "pay.csv", PAY, pay_rows(hours, nominal))
            self.assertEqual([r for r,_ in recalc(path, Table(root / "pay.csv"), oracle)], [0, 0, 0])
