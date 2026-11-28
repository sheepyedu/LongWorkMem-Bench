import tempfile
import unittest
from pathlib import Path

from tasks.w4.quota import bulletins, world
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
