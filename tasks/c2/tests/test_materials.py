"""Pin each release independently of participant-authored code and subscriber actions."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from tasks.c2.scenario import release, setup
from tasks.c2.subscriber import interrupt


def fingerprints():
    digests = []
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp)
        desk = run / "work"
        setup(desk)
        for turn in range(1, 9):
            prompt = release(desk, turn)
            if turn == 7:
                interrupt(run)
            digest = sha256(prompt.encode() + b"\0")
            for path in sorted((desk / "input").rglob("*")):
                if path.is_file():
                    digest.update(path.relative_to(desk).as_posix().encode() + b"\0")
                    digest.update(sha256(path.read_bytes()).digest())
            digests.append(digest.hexdigest())
    return digests


class CalendarMaterials(unittest.TestCase):
    def test_calendar_v1(self):
        expected = json.loads(Path(__file__).with_name("materials.json").read_text())
        self.assertEqual(fingerprints(), expected)
