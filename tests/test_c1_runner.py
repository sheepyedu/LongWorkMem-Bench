import json
import os
import platform
from pathlib import Path
import tempfile
import unittest

from c1.review import audit
from c1.runstate import freeze


class CheckoutTests(unittest.TestCase):
    def test_snapshots_preserve_deletions_modes_and_internal_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            work.mkdir()
            entry = work / "service"
            entry.write_text("old")
            entry.chmod(0o755)
            (work / "inside").symlink_to("service")
            (work / "outside").symlink_to("../private")
            self.assertEqual(freeze(work, root / "first"), ["outside"])
            entry.unlink()
            (work / "inside").unlink()
            self.assertEqual(freeze(work, root / "second"), ["outside"])
            self.assertEqual((root / "first/inside").read_text(), "old")
            self.assertTrue((root / "first/service").stat().st_mode & 0o100)
            self.assertFalse((root / "second/service").exists())
            self.assertFalse((root / "first/outside").is_symlink())
            with self.assertRaises(FileExistsError):
                freeze(work, root / "first")

    def test_audit_reports_missing_receipt_and_invalid_cli_row(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "trace").mkdir()
            (run / "manifest.json").write_text(json.dumps(dict(status="complete", session="s",
                turns=[dict(turn=1, upstream_calls=1)], model="test")))
            (run / "trace/turn-1.jsonl").write_text("not-json\n")
            summary = audit(run)
            self.assertTrue(any("manifest has 1 attempts" in issue for issue in summary["flags"]))
            self.assertTrue(any("turn-1.jsonl:1" in issue for issue in summary["flags"]))

    @unittest.skipUnless(platform.system() == "Darwin" or os.getenv("C1_TEST_DOCKER") == "1",
                         "requires an isolated code backend")
    def test_untouched_starter_only_earns_legacy_compatibility_and_preservation(self):
        from c1 import sandbox, world
        from c1.grade import grade
        backend = "docker" if os.getenv("C1_TEST_DOCKER") == "1" else "seatbelt"
        with tempfile.TemporaryDirectory(dir=os.getenv("C1_TEST_ROOT")) as directory:
            run = Path(directory)
            for turn in range(1, 13):
                work = run / "work"
                world.release(work, turn, "B")
                if turn == 6:
                    stopped = sandbox.shell(work, world.batch_command(True), backend)
                    self.assertNotEqual(stopped["status"], 86)
                    (run / "fault.json").write_text(json.dumps(stopped))
                    freeze(work, run / "fault")
                freeze(work, run / "snapshots" / str(turn))
            result = grade(run, "B", backend)
            earned = {key: item["earned"] for key, item in result["checks"].items() if item["earned"]}
            self.assertTrue(result["valid"], result["infrastructure_errors"])
            self.assertEqual(earned, {"CP1.legacy": 5, "CP1.migration": 2, "CP5.legacy": 5})

    def test_cli_unavailable_tool_is_a_verifiable_client_receipt(self):
        from c1.review import result_value
        rejection = '<tool_use_error>Error: No such tool available: workshop__shell</tool_use_error>'
        self.assertEqual(result_value(rejection), {'client_error': rejection})
        with self.assertRaises(ValueError):
            result_value('unexpected unstructured output')

    def test_dispatch_captures_exact_accepted_shell_call_across_tool_restarts(self):
        import io
        from unittest.mock import patch
        from c1 import sandbox
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / 'work'
            work.mkdir()
            dest, journal = root/'signed', root/'journal.jsonl'
            def write(_work, command, backend):
                (work/'delivery').write_text(command)
                return {'status': 0, 'output': command}
            def serve(commands):
                events = [dict(id=i, method='tools/call', params=dict(name='shell', arguments={'command':cmd}))
                          for i,cmd in enumerate(commands)]
                with patch('sys.stdin',io.StringIO('\n'.join(map(json.dumps,events)))), patch('sys.stdout',io.StringIO()) as output:
                    sandbox.serve(work,'docker',journal,dest,4)
                self.assertNotIn(str(dest),output.getvalue())
            with patch.object(sandbox,'shell',write):
                serve(['one','two','three'])
                self.assertFalse(dest.exists())
                serve(['four','five'])
            self.assertEqual((dest/'delivery').read_text(),'four')
            self.assertEqual((work/'delivery').read_text(),'five')

    def test_transport_timeout_requires_same_payload_retry_and_has_unknown_usage(self):
        from c1.pilot import ALLOWED
        with tempfile.TemporaryDirectory() as temp:
            run=Path(temp)
            trace=run/'trace'
            trace.mkdir()
            (run/'manifest.json').write_text(json.dumps(dict(turns=[dict(turn=1, upstream_calls=2)],
                                                           session='s',status='complete',model='m')))
            wire=dict(model='m',messages=[],tools=[dict(function=dict(name=k)) for k in ALLOWED])
            first=dict(n=1,turn=1,status=502,error='timed out',request=wire)
            second=dict(n=2,turn=1,status=200,request=wire,response=dict(id='response',model='m',
                        usage=dict(prompt_tokens=100,completion_tokens=10),choices=[dict(message={})]))
            (trace/'api-0001.json').write_text(json.dumps(first))
            (trace/'api-0002.json').write_text(json.dumps(second))
            (trace/'turn-1.jsonl').write_text(json.dumps(dict(type='result',is_error=False,session_id='s'))+'\n')
            summary=audit(run)
            self.assertEqual(summary['flags'],[])
            self.assertEqual(summary['retry_attempts'][0]['retry'],'api-0002.json')
            self.assertEqual(summary['totals']['unknown_usage'],1)
            second['request']={**wire,'max_tokens':20}
            (trace/'api-0002.json').write_text(json.dumps(second))
            self.assertTrue(any('matching retry' in issue for issue in audit(run)['flags']))
