import unittest

from tasks.w1.gateway import MODEL, anthropic, stream_events, translate


class GatewayTest(unittest.TestCase):
    def test_model_is_selected_by_host_for_each_session(self):
        query = {"model": "qwen3.8-flash", "max_tokens": 900, "messages": []}
        self.assertEqual(translate(query, {}, model="qwen3.8-flash")["model"], query["model"])
        with self.assertRaises(ValueError):
            translate(query, {}, model=MODEL)

    def test_gpt_sol_uses_supported_low_effort_and_same_output_limit(self):
        model = "gpt-6.1-sol"
        payload = translate({"model":model, "max_tokens":32000, "messages":[]}, {}, model=model)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_completion_tokens"], 32000)
        self.assertNotIn("max_tokens", payload)

    def test_tool_history_and_exact_usage(self):
        memory = {}
        msg = anthropic({"id": "id", "model": MODEL,
                         "usage": {"prompt_tokens": 22, "completion_tokens": 7, "prompt_tokens_details": {"cached_tokens": 12}},
                         "choices": [{"finish_reason":"tool_calls","message":{"reasoning_content":"context",
                                      "tool_calls":[{"id":"t","function":{"name":"mcp__office__shell","arguments":'{"command":"pwd"}'}}]}}]},memory)
        self.assertEqual(msg["usage"]["input_tokens"],10)
        self.assertEqual(list(stream_events(msg))[-1]["type"],"message_stop")
        query = {"model":MODEL,"max_tokens":1200,"system":"business",
                 "messages":[{"role":"assistant","content":msg["content"]},{"role":"user","content":[
                             {"type":"tool_result","tool_use_id":"t","content":[{"type":"text","text":"office"}]},
                             {"type":"text","text":"continue"}]}]}
        translated = translate(query,memory)["messages"]
        self.assertEqual(translated[-3]["reasoning_content"],"context")
        self.assertEqual(translated[-2],{"role":"tool","tool_call_id":"t","content":"office"})
        self.assertEqual(translated[-1]["content"],"continue")
        query["tools"]=[{"name":"Bash","input_schema":{}}]
        with self.assertRaises(ValueError):
            translate(query,memory)

    def test_experimental_limit_and_paid_malformed_tool_are_distinguishable(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        from io import BytesIO
        import json
        from tasks.w1.gateway import Gateway

        query = dict(model=MODEL, max_tokens=32, messages=[dict(role="user",content="test")])
        reply = dict(id="fixture", model=MODEL, choices=[dict(finish_reason="stop", message=dict(content="ok"))],
                     usage={"prompt_tokens":2,"completion_tokens":1})

        def call(gw):
            request = Request(gw.base + "/v1/messages", data=json.dumps(query).encode(),
                              headers={"x-api-key":gw.token, "content-type":"application/json"})
            with urlopen(request) as response:
                return json.load(response)

        def transport(_request, timeout):
            response = BytesIO(json.dumps(reply).encode())
            response.status, response.headers = 200, {}
            return response

        with TemporaryDirectory() as tmp:
            run=Path(tmp)
            (run / "trace").mkdir()
            with Gateway("local-fixture",run) as gw, patch.object(gw.opener,"open",transport):
                # The next actual request crosses both historical pilot thresholds.
                gw.count = 350
                self.assertEqual(call(gw)["content"][0]["text"], "ok")
                for reason, kind in [("length","truncated_tool_arguments"),("tool_calls","invalid_tool_arguments")]:
                    reply["choices"]=[dict(finish_reason=reason,message=dict(tool_calls=[
                        dict(id="no-action",function=dict(name="shell",arguments="{"))]))]
                    with self.assertRaises(HTTPError):call(gw)
                    record=json.loads((run/"trace"/f"api-{gw.count:04}.json").read_text())
                    self.assertEqual((record["upstream_status"],record["failure_kind"]), (200,kind))
                    self.assertEqual(record["response"]["usage"],reply["usage"])
                self.assertFalse(gw.budget_exhausted)
            with Gateway("local-fixture",run,limit=1) as gw:
                gw.count=1
                with self.assertRaises(HTTPError) as err:call(gw)
                self.assertEqual(err.exception.code,400)
                self.assertTrue(gw.budget_exhausted)
