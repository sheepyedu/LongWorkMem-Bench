"""Score the same frozen work under both contracts, without a model or Docker."""

import json
import re
import shutil
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.w1.runstate import freeze, prepare
from tasks.w4.annex_grade import station
from tasks.w4.office import events, invoke
from tasks.w4.outcome_score import score
from tasks.w4.scenario import ROUNDS

from .test_annex import play
from .test_release import fixture


def controls(root):
    base, gold = root / "base", root / "gold"
    fixture(base)
    play(gold, base)
    yield "gold", gold
    for mode in (
        "latest_site",
        "zero_seats",
        "all_twice",
        "no_dispatch",
        "wrong_recipient",
    ):
        target = root / mode
        shutil.copytree(gold, target)
        for event in events(target, 12, None):
            folder = target / "mail" / str(event["turn"]) / event["receipt"]
            path = folder / "payload"
            payload = path.read_text()
            if mode == "latest_site":
                obj = re.search(r"^对象：(.*)$", payload, re.MULTILINE)[1]
                path.write_text(
                    re.sub(
                        r"^服务主站：.*$",
                        "服务主站：" + station(obj, 12),
                        payload,
                        flags=re.MULTILINE,
                    )
                )
            elif mode == "zero_seats":
                path.write_text(
                    re.sub(
                        r"^预留席位：.*$", "预留席位：0", payload, flags=re.MULTILINE
                    )
                )
            elif event["action"] == "deliver":
                if mode == "no_dispatch":
                    shutil.rmtree(folder)
                elif mode == "wrong_recipient":
                    event["recipient"] = "unused@office.test"
                    event["unknown_mailbox"] = True
                    (folder / "event.json").write_text(json.dumps(event))
                else:
                    extra = folder.with_name(folder.name + "-duplicate")
                    shutil.copytree(folder, extra)
                    event.update(receipt=extra.name, sequence=10000 + event["sequence"])
                    (extra / "event.json").write_text(json.dumps(event))
        yield mode, target
    missing = root / "omit_appendix"
    play(missing, base, omit=True)
    yield "omit_appendix", missing
    recovered = root / "recovered"
    fixture(root / "bad_first", "recover")
    play(recovered, root / "bad_first")
    yield "recovered", recovered
    empty = root / "empty"
    prepare(empty)
    shutil.copy(gold / "manifest.json", empty)
    for t in ROUNDS:
        freeze(empty, t, rounds=ROUNDS)
    yield "empty", empty


class OutcomeTest(unittest.TestCase):
    def test_controls(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            for mode, run in controls(root):
                with self.subTest(mode=mode):
                    g = score(run)
                    self.assertEqual(sum(row["maximum"] for row in g["groups"]), 100)
                    releases = [
                        row for row in g["groups"] if row["group"] == "实际履约"
                    ]
                    if mode in ("no_dispatch", "wrong_recipient", "empty"):
                        self.assertEqual(sum(x["earned"] for x in releases), 0)
                    if mode == "gold":
                        self.assertEqual(g["total"], 100)
                    elif mode == "empty":
                        self.assertEqual(g["total"], 0)
                    else:
                        self.assertLess(g["total"], 100)
                    if mode == "recovered":
                        self.assertEqual(
                            releases[-1]["earned"], releases[-1]["maximum"]
                        )
                        self.assertLess(releases[0]["earned"], releases[0]["maximum"])
            gold = root / "gold"
            for turn in (1, 12):
                invoke(
                    gold,
                    turn,
                    None,
                    "deliver",
                    {
                        "subject": "unsolicited",
                        "recipient": "hz.service@office.test",
                        "attachment": "out/manual.md",
                    },
                )
            g = score(gold)
            self.assertEqual(sum(len(x["extras"]) for x in g["groups"]), 2)
            self.assertLess(g["total"], 100)
            with self.assertRaises(ValueError):
                score(root / "base")

    def test_published_run(self):
        public = (
            Path(__file__).resolve().parents[3] / "rollout/w4/deepseek-v4.1-flash/v2"
        )
        with TemporaryDirectory() as td:
            root = Path(td)
            shutil.copy(public / "manifest.json", root)
            with tarfile.open(public / "artifacts.tar.gz") as archive:
                archive.extractall(root, filter="data")
            g = score(root)
            self.assertEqual(g["frozen_total"], 95.4118)
            self.assertEqual(g["total"], 90.1857)
            by_name = {x["group"]: x for x in g["groups"] if x["turn"] == 11}
            self.assertEqual(by_name["历史授权"]["earned"], 4)
            self.assertEqual(by_name["历史实发"]["earned"], 2.5)
            self.assertEqual(len(by_name["实际履约"]["extras"]), 6)


if __name__ == "__main__":
    with TemporaryDirectory() as tmp:
        for label, run in controls(Path(tmp)):
            g = score(run)
            print(label, g["frozen_total"], g["total"])
