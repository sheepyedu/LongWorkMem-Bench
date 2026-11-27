import unittest
from scripts.checkpoint_trial.scoring import decision_component, pair_credit, reserve_case


class CheckpointTrialTest(unittest.TestCase):
    def test_reserve_authorization_gates_partial_credit(self):
        expected=dict(project="P",desk="岗1234",authority="A",decision="BOOK",target="10",change="3")
        self.assertEqual(reserve_case(expected,expected),(True,True,True))
        self.assertEqual(reserve_case({**expected,"change":"4"},expected),(True,True,False))
        self.assertEqual(reserve_case({**expected,"decision":"HOLD"},expected),(True,False,False))
        self.assertEqual(reserve_case({**expected,"authority":"wrong"},expected),(False,False,False))

    def test_counterfactual_coverage_and_duplicates(self):
        goal = {"1":"ok","2":"rejected"}
        opposite = {"1":"rejected","2":"rejected"}
        exact = [["1","ok"],["2","rejected"]]
        def score(rows, strict):
            return decision_component(rows,goal,opposite,4,strict)["new"]
        self.assertEqual(score(exact,4),4)
        self.assertEqual(score(None,0),0)
        self.assertEqual(score([],0),0)
        self.assertEqual(score([exact[0]],0),1.5)
        self.assertEqual(score([exact[1]],0),.5)
        self.assertEqual(score([*exact,exact[0]],0),.5)
        self.assertLess(score([*exact,["extra","ok"]],0),score([exact[0]],0))
        self.assertEqual(score([["1","ok","extra"]],0),0)

    def test_correct_delivery_requires_both_fields_for_full_credit(self):
        expected = ["kit","seal"]
        self.assertEqual(pair_credit(None,expected),0)
        self.assertEqual(pair_credit(["x","x"],expected),0)
        self.assertEqual(pair_credit(["kit","x"],expected),.25)
        self.assertEqual(pair_credit(expected,expected),1)
        self.assertEqual(pair_credit(["kit","x"],expected,["kit","oldseal"]),0)
        self.assertEqual(pair_credit(["kit","x"],expected,["oldkit","seal"]),.25)
        self.assertEqual(pair_credit(expected,expected,expected),1)

    def test_unused_warehouse_records_do_not_gain_under_changed_field_rule(self):
        from tasks.s1.circuit import Circuit
        from scripts.checkpoint_trial.scoring import order_components
        for seed in (17217, 17219, 17231, 17239):
            circuit = Circuit(seed,"A",10,2,2,version=2)
            receipts = []
            for turn,(desk,stage) in enumerate(circuit.schedule,1):
                season = circuit.seasons[desk]
                orders = {t:season.stock[t] for t,_ in season.jobs.get(stage,[])}
                receipts.append(circuit.receipt(turn,{"orders":orders}))
            score = circuit.score(receipts)
            for result in order_components(score,circuit).values():
                self.assertAlmostEqual(result["new"],result["old"])
            self.assertTrue(any(r["new"]>r["old"] for r in order_components(score).values()))
