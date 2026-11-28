import tempfile
import unittest
from pathlib import Path

from tasks.w1.runstate import prepare
from tasks.w4.quota import bulletins, world
from tasks.w4.quota.score import charter
from tasks.w4.tests.bulletin_controls import BulletinReader


class BulletinTests(unittest.TestCase):
    def test_public_terms_resolve_across_loan_return_and_register_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            reader = BulletinReader()
            read = {}
            for day in range(1, 13):
                bulletins.release(work, day)
                folder = work / "inbox" / f"06-{day:02}"
                self.assertFalse((folder / "签发原件.csv").exists())
                for row in reader.read(folder, day, "gold"):
                    key = int(row["流水"])
                    self.assertNotIn(key, read)
                    read[key] = (
                        day,
                        int(row["生效日"]),
                        int(row["到期日"]),
                        row["案号"],
                        row["签发人"],
                        row["性质"],
                        int(row["额度"]),
                        int(row["优先号"]),
                    )
                if day in (3, 8):
                    prior = work / "inbox" / f"06-{day - 1:02}"
                    self.assertEqual(list(prior.iterdir()), [])
            self.assertEqual(read, {row[0]: row[1:] for row in bulletins.documents()})
            self.assertEqual(len(read), 132)
            self.assertEqual(len(world.documents()), 48)

    def test_withdrawal_note_preserves_the_renewal_as_a_separate_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            for revised in (False, True):
                work = prepare(Path(tmp) / str(revised))
                world.initialize(
                    work, clarified=True, promise=True, mixed=True, renewal_note=revised
                )
                guide = (work / "input/办公室/发布规程.txt").read_text()
                self.assertEqual(bulletins.RENEWAL_NOTE in guide, revised)
        # The original J02 approval 2010 and its independent renewal 9015
        # refer to the same historical number but have different legal lifetimes.
        self.assertIn(2010, world.WITHDRAW[9])
        self.assertEqual(charter("J02", 9, 9, bulletins.documents()), ("9015", 3, 2))
