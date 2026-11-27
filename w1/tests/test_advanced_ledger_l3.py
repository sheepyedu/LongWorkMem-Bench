from pathlib import Path
from decimal import Decimal
from tempfile import TemporaryDirectory
import unittest

from w1 import advanced_ledger_l3 as ledger
from w1.runstate import prepare, freeze
from w1.scoring_tables import Table
from w1.world import _csv


class LedgerMigrationTests(unittest.TestCase):
    def test_return_keeps_original_pack_and_credit_keeps_original_rounded_splits(self):
        docs = {
            '订单':[dict(site=s,po='P',line=1,sku='S') for s in ('东','北')],
            '包装':[dict(sku='S',unit='箱',effective=d,factor=n) for d,n in
                  [('2025-06-01',4),('2025-07-01',10)]],
            '仓储':[dict(site='东',event='W',revision=1,posted='2025-06-01',approved='2025-06-02',
                       status='有效',po='P',line=1,unit='箱',qty=2)],
            '发票':[dict(site='北',event='I',revision=1,posted='2025-06-01',approved='2025-06-02',
                       status='有效',po='P',line=1,currency='CNY',amount='3.33')],
            '认领':[dict(site='北',source='invoice',event='I',revision=rev,signed=day,decision='核准',
                       part=part,target_site=site,po='P',line=1,bps=bps) for rev,day,part,site,bps in
                  [(1,'2025-06-30',1,'东',5000),(1,'2025-06-30',2,'北',5000),
                   (2,'2025-07-02',1,'北',10000)]],
        }
        with TemporaryDirectory() as tmp:
            work=Path(tmp)
            _csv(work/'input/财务共享/售后/冲抵通知.csv',ledger.NOTICE,[
                ('东','A',1,'2025-07-03','2025-07-03','核准','receipt','W',1,0),
                ('北','B',1,'2025-07-03','2025-07-03','核准','invoice','I',0,5000)])
            rows=ledger.credit_evidence(work,docs)
            self.assertEqual([(r['target_site'],r['net_change'],r['invoice_change']) for r in rows],
                             [('东',-4,0),('东',0,Decimal('-.84')),('北',0,Decimal('-.83'))])

    def test_retired_sources_reference_and_missing_credit_evidence(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)/'run'
            work = prepare(run)
            for turn in range(1,10):
                ledger.release(work,turn,'A',3,114)
                if turn == 1:
                    self.assertIn('无法调阅', (work/'inbox/GL-0527.eml').read_text())
                if turn in (3,4):
                    path = work/'input/财务共享/流转/0626'
                    self.assertEqual((path/'应付归集.xlsx').exists(), turn==3)
                    self.assertEqual((path/'应付归集（会签稿）.xlsx').exists(),turn==3)
                    self.assertTrue((path/'订货与基础资料.xlsx').is_file())
                ledger.reference(run,turn,'A',3,114)
                freeze(run,turn)
            scores=ledger.checks(run,'A',3,114)
            self.assertEqual(sum(s[0] for s in scores.values()),40)
            self.assertEqual(sum(s[1] for s in scores.values()),40)
            support=run/'snapshots/5/credit_support.csv'
            self.assertGreater(len(Table(support).rows), 8)
            support.unlink()
            self.assertEqual(sum(s[0] for s in ledger.checks(run,'A',3,114).values()),36)
