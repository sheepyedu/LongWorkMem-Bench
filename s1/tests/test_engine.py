import os
import unittest

from benchmark_protocol import PUBLIC_SEED
from s1.circuit import Circuit, REGISTER_PHASE
from s1.engine import exchange, open_engine
from s1.tests import test_s1_circuit as fixtures


@unittest.skipUnless(os.environ.get("S1_TEST_DOCKER") == "1", "requires circuit image")
class EngineIntegrationTest(unittest.TestCase):
    def test_eighty_turn_handover_and_receipt_parity(self):
        c = Circuit(PUBLIC_SEED, "A", 10, 2, 2, version=3)
        golden = fixtures.SingleCircuitTest().play_public(c)
        history, memo, receipts = "handover", "", []
        with open_engine(PUBLIC_SEED, "A", 10, 2, 2) as (engine,image):
            self.assertTrue(image.startswith("sha256:"))
            for turn,(desk,stage) in enumerate(c.schedule,1):
                self.assertEqual(exchange(engine,"prompt",turn,history,memo), c.prompt(turn,history,memo))
                wanted = golden[turn-1]
                if "register" in wanted:
                    command = {"register": {k:{REGISTER_PHASE[stage]:v} for k,v in wanted["register"].items()}}
                else:
                    command = {"orders":wanted["booked"]}
                if turn == 1:
                    with self.assertRaises(ValueError):
                        exchange(engine,"submit",turn,{},history)
                if turn == 40:
                    command["note"] = "开幕记录" * 2000
                receipt = exchange(engine,"submit",turn,command,history)
                self.assertEqual(receipt,c.submission(turn,command,history))
                memo = receipt.get("memo",memo)
                receipts.append(receipt)
        self.assertEqual(c.score(receipts)["total"],100)
