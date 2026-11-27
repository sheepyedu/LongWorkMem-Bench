from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tasks.w1 import advanced_consignment as audit
from tasks.w1.advanced_ledger_score import write_rows

from tasks.w1 import advanced_ledger_l4 as ledger
from tasks.w1.runstate import prepare,freeze
from tasks.w1.scoring_tables import Table


class ConsignmentTests(unittest.TestCase):
    def test_symmetric_local_candidates_but_only_one_consistent_full_batch(self):
        slips=[dict(ticket=str(i),qty=q,amount=a) for i,(q,a) in enumerate(
            [(4,2),(3,1),(4,3),(6,2),(3,2),(5,2),(2,1),(3,3)])]
        bills=[dict(site='江东',batch='A',bill=str(i),print_line=i,ticket_count=2,
                    total_qty=q,total_amount=a) for i,(q,a) in enumerate([(7,5),(7,4),(9,4),(7,3)])]
        result=[(r['status'],r['tickets']) for r,_,_ in audit.resolve_group(slips,bills,{}, {})]
        self.assertEqual(result,[('BOOKED','0|7'),('BOOKED','1|2'),('BOOKED','3|4'),('BOOKED','5|6')])
        bills[-1]['total_amount']='3.01'
        result=[(r['status'],r['tickets']) for r,_,_ in audit.resolve_group(slips,bills,{}, {})]
        self.assertEqual(result,[('CONFLICT','')]*4)

    def test_confirmable_bills_within_an_ambiguous_batch_and_a_signed_assignment(self):
        slips=[dict(ticket=str(i),qty=q,amount=a) for i,(q,a) in enumerate(
            [(7,3),(1,1),(6,2),(1,3),(7,3),(4,2),(4,1),(4,3)])]
        bills=[dict(site='江东',batch='B',bill=str(i),print_line=i,ticket_count=2,
                    total_qty=q,total_amount=a) for i,(q,a) in enumerate([(11,4),(10,5),(8,6),(5,3)])]
        calc=lambda notes:[(r['status'],r['tickets']) for r,_,_ in audit.resolve_group(slips,bills,{},notes)]
        self.assertEqual(calc({}),[('MULTIPLE',''),('BOOKED','2|7'),('MULTIPLE',''),('BOOKED','1|5')])
        self.assertEqual(calc({('江东','B','0','4'):(2,'指定')}),
                         [('BOOKED','4|6'),('BOOKED','2|7'),('BOOKED','0|3'),('BOOKED','1|5')])

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
            path=base/'5/consignment.csv'
            rows=Table(path).rows
            for row in rows:
                row['tickets']=' | '.join(reversed(row['tickets'].split('|')))
            write_rows(path,ledger.FORM,rows[::-1])
            self.assertEqual(sum(x[0] for x in ledger.checks(run,'A',4,431).values()),40)
            pending=next(r for r in rows if r['status']=='MULTIPLE')
            pending['status'],pending['tickets']='BOOKED','guessed'
            write_rows(path,ledger.FORM,rows)
            score=ledger.checks(run,'A',4,431)['ledger.consignment.current']
            self.assertAlmostEqual(score[0],2*111/112)
            path.write_bytes(b'\xff')
            self.assertEqual(sum(x[0] for x in ledger.checks(run,'A',4,431).values()),38)
            path.unlink()
            self.assertEqual(sum(x[0] for x in ledger.checks(run,'A',4,431).values()),38)

            # A chain of identical stubs with BOOKED but no identified slips is not a filing.
            for row in second:
                row['status'],row['tickets']='BOOKED',''
            for file in [base/'2/consignment.csv',*(base/str(t)/'frozen/consignment-06.csv' for t in range(3,10))]:
                write_rows(file,ledger.FORM,second)
            scores=ledger.checks(run,'A',4,431)
            for stage in ('reported','retained'):
                self.assertEqual(scores['ledger.consignment.freeze.'+stage][0],0)

    def test_unsigned_late_and_superseded_endorsements_are_not_posting_instructions(self):
        with TemporaryDirectory() as tmp:
            work=Path(tmp)
            (work/'inbox').mkdir()
            ledger.publish(work,1,123)
            cabinet=work/audit.CABINET
            bills=audit.read_pages(cabinet/'0626/对账联.xlsx','结算')
            g={idx:(site,batch,slips,items) for site,batch,idx,slips,items in ledger.forms(123) if site=='江东'}
            def note_key(group,bill,ticket):
                site,batch,slips,items=g[group]
                return site,batch,items[bill][0],slips[ticket][0]
            _,first=audit.review_records(cabinet,audit.JUNE,bills)
            self.assertNotIn(note_key(1,2,0),first)  # supplier comment
            self.assertNotIn(note_key(5,1,1),first)  # future AP signature
            self.assertEqual(first[note_key(4,0,4)],(1,'排除'))
            ledger.publish(work,2,123)
            ledger.publish(work,5,123)
            amended,june=audit.review_records(cabinet,audit.JUNE,bills)
            site,batch,_,items=g[3]
            self.assertEqual(amended[site,batch,items[1][0]][0],2)  # unsigned rev 8
            self.assertEqual(june[note_key(4,0,4)],(2,'解除'))
            _,july=audit.review_records(cabinet,audit.JULY,bills)
            self.assertEqual(july[note_key(4,0,4)],(3,'指定'))
            self.assertEqual(july[note_key(5,1,1)],(1,'排除'))
            self.assertNotIn(note_key(6,3,0),july)  # signed July 12
            self.assertNotIn(note_key(6,3,1),july)  # July 4, consult only
