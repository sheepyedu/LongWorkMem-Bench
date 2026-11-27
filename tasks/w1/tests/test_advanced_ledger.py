from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tasks.w1 import advanced_ledger as ledger
from tasks.w1.advanced_ledger_score import accounting, agenda, changes, write_rows
from tasks.w1.scoring_tables import Table
from tasks.w1.runstate import prepare, freeze
from tasks.w1.world import _csv


class AdvancedLedgerTests(unittest.TestCase):
    def test_signed_versions_package_date_and_cross_site_remainder(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            base = work/'input/财务共享'
            rows = {
                '订单': [('东','P',1,'甲','SKU',10,'1.15'), ('北','P',1,'甲','SKU',5,'1.15')],
                '包装': [('SKU','箱','2025-06-01',2), ('SKU','箱','2025-06-20',6)],
                '汇率': [('HKD','2025-06-01','0.7'), ('HKD','2025-06-20','0.9')],
                '仓储': [('东','R',1,'2025-06-18','2025-06-25','有效','P',1,'箱',3),
                         ('东','R',1,'2025-06-18','2025-06-25','有效','P',1,'箱',3),
                         ('东','R',2,'2025-06-18','2025-07-01','撤销','P',1,'箱',3),
                         ('北','R',1,'2025-07-03','2025-06-30','有效','P',1,'件',4)],
                '发票': [('北','I',1,'2025-06-21','2025-06-25','有效','错单',6,'HKD','10.01')],
                '认领': [('invoice','北','I',1,'2025-06-30','核准',1,'东','P',1,5000),
                         ('invoice','北','I',1,'2025-06-30','核准',2,'北','P',1,5000),
                         ('invoice','北','I',2,'2025-07-01','撤回',1,'北','P',1,10000),
                         ('invoice','北','I',9,'2025-06-30','提议',1,'北','P',1,10000)],
            }
            ledger.workbook(base/'正本.xlsx', {k:(ledger.SCHEMAS[k],v) for k,v in rows.items()})
            _csv(base/'收文登记'/'一.csv','file,sheet,status', [('正本.xlsx',k,'签收') for k in rows])
            june = accounting(work,'2025-06-30')
            july = accounting(work,'2025-07-08')
            self.assertEqual([(r['net'], r['invoiced_amount']) for r in june[0]],
                             [(6,Decimal('4.51')),(0,Decimal('4.50'))])
            self.assertEqual([(r['net'], r['invoiced_amount']) for r in july[0]],[(0,0),(4,0)])
            self.assertFalse(june[1])
            self.assertEqual(july[1],[dict(site='北',source='invoice',id='I',po='错单',line=6)])
            bridge, routes = changes(june,july)
            self.assertEqual([(r['net_change'], r['invoice_change']) for r in bridge],
                             [(-6,Decimal('-4.51')),(4,Decimal('-4.50'))])
            self.assertEqual(routes,[dict(site='北',source='invoice',id='I',before='东/P/1|北/P/1',after='PENDING')])

    def test_same_seed_procurement_is_byte_identical_across_variant(self):
        with TemporaryDirectory() as tmp:
            offices = {}
            for variant in ('A','B'):
                w = prepare(Path(tmp)/variant)
                for turn in range(1,6):
                    ledger.release(w,turn,variant,2,622)
                offices[variant] = {str(p.relative_to(w)):p.read_bytes() for p in w.rglob('*') if p.is_file()}
            self.assertEqual(offices['A'],offices['B'])
            self.assertNotEqual(ledger.batches(2,622)[1]['订单'],ledger.batches(2,623)[1]['订单'])

    def test_reference_scores_both_levels_and_late_correction_cannot_replace_june(self):
        for level in (1, 2):
            with self.subTest(level=level), TemporaryDirectory() as tmp:
                run = Path(tmp) / 'company'
                work = prepare(run)
                for turn in range(1, 10):
                    ledger.release(work, turn, 'A', level, 1083)
                    ledger.reference(run, turn, 'A', level, 1083)
                    freeze(run, turn)
                scores = ledger.checks(run, 'A', level, 1083)
                self.assertEqual(sum(x[0] for x in scores.values()), 40)
                self.assertEqual(sum(x[1] for x in scores.values()), 40)
                june = run / 'snapshots/9/frozen/2025-06.csv'
                june.write_bytes((run / 'snapshots/5/current.csv').read_bytes())
                self.assertEqual(ledger.checks(run, 'A', level, 1083)['ledger.freeze.retained'][0], 0)

    def test_broken_csv_is_scored_and_omissions_do_not_match(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            path = run / 'snapshots/1/current.csv'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'bad,keys\n\xff')
            scores = ledger.checks(run, 'B', 2, 1083)
            self.assertEqual(sum(x[0] for x in scores.values()), 0)

    def test_derived_reports_use_filed_versions_with_complete_unique_order_keys(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)/'company'
            work = prepare(run)
            for turn in range(1,10):
                ledger.release(work,turn,'B',1,1083)
                ledger.reference(run,turn,'B',1,1083)
                freeze(run,turn)
            snapshots = run/'snapshots'
            frozen = snapshots/'3/frozen/2025-06.csv'
            june = Table(frozen).rows
            for row in june:
                row['line'] = row['line']+'.0'
            write_rows(frozen,ledger.LEDGER,june)
            self.assertEqual(sum(v[0] for v in ledger.checks(run,'B',1,1083).values()),40)
            for row in june:
                row['line'] = str(int(Decimal(row['line'])))
            june[0].update(net='0',qty_diff='-13',invoiced_amount='200001.51',
                           amount_diff='200001.51',flags='QA')
            write_rows(frozen,ledger.LEDGER,june)
            totals,priority = agenda(june)
            write_rows(snapshots/'4/meeting.csv',ledger.MEETING,totals)
            write_rows(snapshots/'4/priority.csv',ledger.PRIORITY,priority)
            current = snapshots/'5/current.csv'
            july = Table(current).rows
            july[0].update(net='5',invoiced_amount='100001.00')
            write_rows(current,ledger.LEDGER,july)
            bridge,_ = changes((june,[],{}),(july,[],{}))
            write_rows(snapshots/'5/bridge.csv',ledger.BRIDGE,bridge)
            scores = ledger.checks(run,'B',1,1083)
            for item in ['meeting.counts','meeting.exposure','meeting.priority','bridge']:
                self.assertEqual(scores['ledger.'+item][0],scores['ledger.'+item][1],item)
            self.assertLess(scores['ledger.current.warehouse'][0],3)
            write_rows(frozen, ledger.LEDGER, june[:-1]+[june[0]])
            scores = ledger.checks(run,'B',1,1083)
            for item in ['meeting.counts','meeting.exposure','meeting.priority','bridge']:
                self.assertEqual(scores['ledger.'+item][0],0,item)
