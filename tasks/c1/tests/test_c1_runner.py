import json
import os
import platform
from pathlib import Path
import tempfile
import unittest

from tasks.c1.review import audit
from tasks.c1.runstate import freeze


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


    def test_cli_unavailable_tool_is_a_verifiable_client_receipt(self):
        from tasks.c1.review import result_value
        rejection = '<tool_use_error>Error: No such tool available: workshop__shell</tool_use_error>'
        self.assertEqual(result_value(rejection), {'client_error': rejection})
        with self.assertRaises(ValueError):
            result_value('unexpected unstructured output')

    def test_dispatch_captures_exact_accepted_shell_call_across_tool_restarts(self):
        import io
        from unittest.mock import patch
        from tasks.c1 import sandbox
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
        from tasks.c1.pilot import ALLOWED
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

    def test_each_fresh_shift_verifies_its_own_session_and_empty_history(self):
        from tasks.c1.pilot import ALLOWED
        with tempfile.TemporaryDirectory() as temp:
            run=Path(temp)
            trace=run/'trace'
            trace.mkdir()
            turns=[]
            for i,t in enumerate((1,5,7),1):
                session=f'shift-{t}'
                turns.append(dict(turn=t,session=session,upstream_calls=1))
                prompt=f'委托 {t}'
                (trace/f'prompt-{t}.txt').write_text(prompt)
                (trace/f'turn-{t}.jsonl').write_text(json.dumps(dict(type='result',is_error=False,session_id=session))+'\n')
                wire=dict(model='m',messages=[dict(role='system',content='desk'),dict(role='user',content=prompt)],
                          tools=[dict(function=dict(name=k)) for k in ALLOWED])
                packet=dict(n=i,turn=t,status=200,request=wire,response=dict(id=f'reply-{i}',model='m',
                            usage=dict(prompt_tokens=5,completion_tokens=2),choices=[dict(message={})]))
                (trace/f'api-{i:04}.json').write_text(json.dumps(packet))
            (run/'manifest.json').write_text(json.dumps(dict(turns=turns,rotation_turns=[5,7],session='shift-1',status='complete',model='m')))
            self.assertEqual(audit(run)['flags'],[])
            packet['request']['messages'].insert(1,dict(role='assistant',content='old conversation'))
            (trace/'api-0003.json').write_text(json.dumps(packet))
            self.assertTrue(any('fresh shift' in flag for flag in audit(run)['flags']))

    def test_budget_terminal_tool_still_requires_matching_host_evidence(self):
        from tasks.c1.pilot import ALLOWED

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            trace = run / "trace"
            trace.mkdir()
            tool = next(iter(ALLOWED))
            args, value = {"command": "pwd"}, {"status": 0, "output": "/workspace"}
            manifest = dict(turns=[], model="m", session="s", status="budget_exhausted",
                            budget_exhausted=True, limit=1)
            wire = dict(model="m", messages=[], tools=[{"function": {"name": tool}}])
            call = dict(id="last", function=dict(name=tool, arguments=json.dumps(args)))
            response = dict(id="reply", model="m", usage=dict(prompt_tokens=1, completion_tokens=1),
                            choices=[dict(message=dict(tool_calls=[call]))])
            events = [
                dict(type="assistant", message=dict(content=[dict(type="tool_use", name=tool, id="last", input=args)])),
                dict(type="user", message=dict(content=[dict(type="tool_result", tool_use_id="last", content=json.dumps(value))])),
                dict(type="result", session_id="s", is_error=True),
            ]
            (run / "manifest.json").write_text(json.dumps(manifest))
            (trace / "api-0001.json").write_text(json.dumps(dict(n=1, turn=1, status=200, request=wire, response=response)))
            (trace / "turn-1.jsonl").write_text("\n".join(map(json.dumps, events)))
            journal = trace / "tools-1.jsonl"
            journal.write_text(json.dumps(dict(args=args, result=value)))
            report = audit(run)
            self.assertEqual(report["flags"], [])
            self.assertEqual(report["unforwarded_at_budget"][0]["receipt"], "api-0001.json")
            journal.write_text(json.dumps(dict(args=args, result={"status": 1})))
            self.assertTrue(any("journal differs" in item for item in audit(run)["flags"]))
