import unittest

from w1.gateway import MODEL, anthropic, stream_events, translate


class GatewayTest(unittest.TestCase):
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
