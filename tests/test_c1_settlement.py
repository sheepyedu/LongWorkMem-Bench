import json
import tempfile
import unittest
from pathlib import Path

from c1 import settlement as world
from c1.settlement_grade import ledger, matches
from c1.settlement_reference import solve


class SettlementTests(unittest.TestCase):
    def test_all_deadlines_alternate_implementation_and_pairing(self):
        for level in (1,2):
            with tempfile.TemporaryDirectory() as tmp:
                for v in ('A','B'):
                    work=Path(tmp)/v; inp=work/'input'
                    for turn in range(1,7):
                        world.release(work,turn,v,119,level)
                        if turn==4:continue
                        plan=json.loads((inp/'jobs'/f'{world.NAMES[turn-1]}.json').read_text())
                        expected=ledger(inp,plan); alternate=solve(inp,plan)
                        for field in expected:self.assertTrue(matches(alternate,expected,field),(level,v,turn,field))
                    for p in (inp/'jobs').glob('archive-*.json'):
                        plan=json.loads(p.read_text());exp=ledger(inp,plan);got=solve(inp,plan)
                        self.assertTrue(all(matches(got,exp,f) for f in exp))
                a,b=(Path(tmp)/v/'input' for v in ('A','B'))
                differences=[p.relative_to(a).as_posix() for p in a.rglob('*') if p.is_file() and p.read_bytes()!=(b/p.relative_to(a)).read_bytes()]
                self.assertEqual(differences,['handover.txt'])
                plan=json.loads((a/'jobs/close.json').read_text());self.assertNotEqual(ledger(a,plan)['audit'],ledger(b,plan)['audit'])

    def test_semantic_rows_preserve_multiplicity_and_leading_zeroes(self):
        expected={'accounts':[['ops','01',0],['ops','1',3]]}
        self.assertTrue(matches({'accounts':expected['accounts'][::-1]},expected,'accounts'))
        self.assertFalse(matches({'accounts':expected['accounts'][:1]*2},expected,'accounts'))
