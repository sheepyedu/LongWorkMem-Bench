from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_ledger_l4 as ledger
from w1.runstate import prepare,freeze
from w1.scoring_tables import Table


class ConsignmentTests(unittest.TestCase):
    def test_reference_preserves_stage_scores_and_records_ambiguous_bills(self):
        with TemporaryDirectory() as tmp:
            run=Path(tmp)/'run'
            work=prepare(run)
            for turn in range(1,10):
                ledger.release(work,turn,'A',4,431)
                ledger.reference(run,turn,'A',4,431)
                freeze(run,turn)
            scores=ledger.checks(run,'A',4,431)
            self.assertEqual(sum(x[0] for x in scores.values()),40,scores)
            self.assertEqual(sum(x[1] for x in scores.values()),40)
            base=run/'snapshots'
            first=Table(base/'1/consignment.csv').rows
            second=Table(base/'2/consignment.csv').rows
            states=lambda rows:{(r['site'],r['batch'],r['bill']):r['status'] for r in rows}
            self.assertEqual(set(states(first).values()),{'BOOKED','MULTIPLE','CONFLICT'})
            self.assertNotEqual(states(first),states(second))
            self.assertFalse((work/'input/财务共享/寄售/0626/消耗联.xlsx').exists())
            self.assertTrue((base/'3/frozen/consignment-06.csv').is_file())
            (base/'5/consignment.csv').unlink()
            self.assertEqual(sum(x[0] for x in ledger.checks(run,'A',4,431).values()),38)
