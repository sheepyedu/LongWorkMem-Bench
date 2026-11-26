import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from w1 import paired
from w1.gateway import MODEL


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class PairedTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)

    def make(self, name, model, seed=431, variant="A", retry=False):
        run = self.base / name
        trace = run / "trace"
        trace.mkdir(parents=True)
        turns, n = [], 0
        for turn in range(1, 10):
            prompt = f"turn {turn} in accounting"
            (trace / f"prompt-{turn}.txt").write_text(prompt)
            terminal = {"type":"result","subtype":"success","is_error":False,"session_id":name}
            save(trace / f"turn-{turn}.jsonl", terminal)
            payload = {"model":model, "messages":[{"role":"user","content":prompt}]}
            failure = turn == 3 and retry
            if failure:
                n += 1
                save(trace / f"api-{n:04}.json", {"n":n, "turn":turn, "request":payload,
                     "status":503, "error":"upstream unavailable", "start":float(n),"end":n+.5})
            n += 1
            save(trace / f"api-{n:04}.json", {"n":n,"turn":turn,"request":payload,"status":200,"start":float(n),"end":n+.5,
                 "response":{"model":model,"id":f"{name}-{n}","choices":[{"finish_reason":"stop","message":{"content":"ok"}}],
                             "usage":{"prompt_tokens":100,"completion_tokens":10}}})
            turns.append({"turn":turn,"upstream_calls":2 if failure else 1,
                          "public_digest":hashlib.sha256(prompt.encode()).hexdigest()})
        save(run / "manifest.json", dict(task="W1-advanced",level=1,variant=variant,seed=seed,session=name,
             claude="2.1",backend="docker",docker_image="sha256:office",status="complete",model=model,
             limit=350,turns=turns,file_hashes={k: 'c'*64 for k in ('gateway.py', 'pilot.py', 'office.py', 'mail.py', 'runstate.py')},isolation={"status":0}))
        return run

    def change(self, file, **kwargs):
        obj = json.loads(file.read_bytes())
        obj.update(kwargs)
        save(file, obj)

    @staticmethod
    def grade(run):
        m = json.loads((run / "manifest.json").read_bytes())
        earned = 65 if m["model"] == MODEL else (55 if m["variant"] == "A" else 59)
        return {"total":earned,"scorer_version":"v1","items":{
            "ledger.a":{"department":"ledger","earned":earned-35,"max":40},
            "pay.b":{"department":"pay","earned":20,"max":35}, "mail3.c":{"department":"mail","earned":15,"max":25}}}

    def test_complete_pairs_and_proven_retry(self):
        ds = self.make("sd", MODEL, seed=1733, retry=True)
        qw = self.make("sq", "qwen3.8-flash", seed=1733)
        ds2 = self.make("td", MODEL, seed=2671, variant="B")
        qw2 = self.make("tq", "qwen3.8-flash", seed=2671, variant="B")
        with patch("w1.paired.grade", side_effect=self.grade):
            result = paired.compare([qw2, ds, qw, ds2])
        self.assertEqual(result["split"],"holdout")
        self.assertEqual(result["mean_paired_gap"],8)
        self.assertEqual(result["paired_outcomes"], {"deepseek_higher":2, "ties":0, "qwen_higher":0})
        self.assertEqual(result["gap_by_seed"], {1733:10, 2671:6})
        self.assertEqual(result["model_means"][MODEL]["range"], [65, 65])
        self.assertEqual(result["model_means"][MODEL]["perfect_runs"], 0)
        self.assertEqual(result["model_means"][MODEL]["total"],65)
        self.assertEqual(result["model_means"][MODEL]["stages"]["mail"],15)
        self.assertEqual(result["model_means"]["qwen3.8-flash"]["stages"]["ledger"],22)
        summary = result["pairs"][0]["models"][MODEL]
        self.assertEqual(summary["usage"]["successful"],9)
        self.assertEqual(summary["usage"]["attempts"],10)
        self.assertEqual(summary["usage"]["input"],900)
        self.assertEqual(summary["retries"],[{"turn":3,"failed_attempt":3,"status":503,"successful_attempt":4}])

    def test_mixed_splits_levels_duplicate_or_missing_model(self):
        a = self.make("a", MODEL)
        b = self.make("b", "qwen3.8-flash")
        c = self.make("c", MODEL, seed=1733)
        d = self.make("d", "qwen3.8-flash", seed=1733)
        with patch("w1.paired.grade", side_effect=self.grade):
            for runs in ([a], [a, b, a], [a,b,c,d]):
                with self.subTest(runs=runs), self.assertRaises(ValueError):
                    paired.compare(runs)
            self.change(d / "manifest.json", seed=431, level=2)
            self.change(c / "manifest.json", seed=431, level=2)
            with self.assertRaises(ValueError):
                paired.compare([a,b,c,d])

    def test_mismatched_environment_and_public_digest_rejected(self):
        a = self.make("a", MODEL)
        b = self.make("b", "qwen3.8-flash")
        path = b / "manifest.json"
        saved = json.loads(path.read_bytes())
        with patch("w1.paired.grade", side_effect=self.grade):
            for change in ({"claude":"other"},{"docker_image":"sha256:other"},{"limit":400},
                           {"turns":[dict(t,public_digest="a"*64) for t in saved["turns"]]}):
                with self.subTest(change=list(change)), self.assertRaises(ValueError):
                    save(path, dict(saved,**change))
                    paired.compare([a,b])
            save(path,saved)

    def test_mismatched_client_and_exposed_score_keys_rejected(self):
        a = self.make("a", MODEL)
        b = self.make("b", "qwen3.8-flash")
        path = b / "manifest.json"
        original = json.loads(path.read_bytes())
        with patch("w1.paired.grade", side_effect=self.grade):
            self.change(path, file_hashes=dict(original["file_hashes"], **{"office.py": "d"*64}))
            with self.assertRaisesRegex(ValueError, "harness"):
                paired.compare([a,b])
            save(path, original)
            private = {"scorer_version": "w1-advanced/1", "items": {"pay.workbook_edited_hours": {"earned": 2}}}
            f = b / "trace/api-0002.json"
            payload = json.loads(f.read_bytes())["request"]
            payload["messages"].append({"role": "tool", "content": json.dumps(private)})
            self.change(f, request=payload)
            with self.assertRaisesRegex(ValueError, "scor"):
                paired.compare([a,b])

    def test_missing_model_and_unrecovered_attempt_rejected(self):
        a = self.make("a", MODEL, retry=True)
        b = self.make("b", "qwen3.8-flash")
        f = a / "trace/api-0004.json"
        old = json.loads(f.read_bytes())
        with patch("w1.paired.grade", side_effect=self.grade):
            for change in ({"request":dict(old["request"],messages=[])},
                           {"response":dict(old["response"],model="some-other-model")},
                           {"response":dict(old["response"],model=None)},
                           {"response":dict(old["response"],id=None)},
                           {"response":dict(old["response"],usage=None)}):
                with self.subTest(change=str(change)[:40]), self.assertRaises(ValueError):
                    save(f,dict(old,**change))
                    paired.compare([a,b])
            save(f,old)
            self.change(a/"trace/api-0003.json",status=403)
            with self.assertRaises(ValueError):
                paired.compare([a,b])
            (a/"trace/api-0003.json").unlink()
            with self.assertRaises(ValueError):
                paired.compare([a,b])

    def test_incomplete_round_with_successful_api_receipt(self):
        a = self.make("a", MODEL)
        b = self.make("b", "qwen3.8-flash")
        with patch("w1.paired.grade", side_effect=self.grade):
            self.change(b/"trace/turn-9.jsonl",is_error=True,subtype="error")
            with self.assertRaises(ValueError):
                paired.compare([a,b])
