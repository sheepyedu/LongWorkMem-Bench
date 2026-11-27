"""Loopback-only Anthropic Messages adapter for Chat Completions.

The full upstream message and actual usage receipt are kept outside the office.
Claude Code owns session history, tool selection and tool execution.
"""
import contextlib
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.request

MODEL = "deepseek-v4-1-flash-261017"
URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def plain(value):
    if isinstance(value, str):
        return value
    return "\n".join(block.get("text", "") for block in value if block.get("type") == "text")


OFFICE_TOOLS = frozenset("mcp__office__" + name for name in ("shell", "draft", "deliver"))


def translate(query, reasoning, allowed=OFFICE_TOOLS, *, model=MODEL):
    if query["model"] != model:
        raise ValueError("Only the configured model is available")
    messages = []
    if query.get("system"):
        messages.append({"role": "system", "content": plain(query["system"])})
    for turn in query["messages"]:
        role, parts = turn["role"], turn["content"]
        if isinstance(parts, str):
            messages.append({"role": role, "content": parts})
            continue
        if role == "assistant":
            message = {"role": role, "content": plain(parts) or None}
            calls = [{"id": p["id"], "type": "function",
                      "function": {"name": p["name"], "arguments": json.dumps(p["input"], ensure_ascii=False)}}
                     for p in parts if p["type"] == "tool_use"]
            if calls:
                message["tool_calls"] = calls
                previous = reasoning.get(calls[0]["id"])
                if previous is not None:
                    message["reasoning_content"] = previous
            messages.append(message)
        else:
            for block in parts:
                if block["type"] == "tool_result":
                    messages.append({"role": "tool", "tool_call_id": block["tool_use_id"],
                                     "content": plain(block.get("content", ""))})
            body = plain(parts)
            if body:
                messages.append({"role": "user", "content": body})
    payload = {"model": model, "messages": messages, "max_tokens": min(query["max_tokens"], 16384), "stream": False}
    if any(t["name"] not in allowed for t in query.get("tools", [])):
        raise ValueError("Unexpected tool in isolated Claude Code process")
    if query.get("tools"):
        payload["tools"] = [{"type": "function", "function": {"name": t["name"],
                "description": t.get("description",""), "parameters": t["input_schema"]}} for t in query["tools"]]
    return payload


def anthropic(reply, reasoning):
    choice = reply["choices"][0]
    obj = choice["message"]
    blocks = []
    if obj.get("content"):
        blocks.append({"type": "text", "text": obj["content"]})
    for t in obj.get("tool_calls") or []:
        if "reasoning_content" in obj:
            reasoning[t["id"]] = obj["reasoning_content"]
        args = json.loads(t["function"]["arguments"])
        blocks.append({"type": "tool_use", "id": t["id"], "name": t["function"]["name"], "input": args})
    usage = reply["usage"]
    cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    return {"id": reply["id"], "model": reply["model"], "type": "message", "role": "assistant",
            "content": blocks, "stop_sequence": None,
            "stop_reason": {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}[choice["finish_reason"]],
            "usage": {"input_tokens": usage["prompt_tokens"]-cached, "cache_read_input_tokens": cached,
                      "cache_creation_input_tokens": 0, "output_tokens": usage["completion_tokens"]}}


def stream_events(message):
    yield {"type": "message_start", "message": {**message, "content": [], "stop_reason": None,
                                              "usage": {**message["usage"], "output_tokens": 0}}}
    for i, block in enumerate(message["content"]):
        value = {"text": ""} if block["type"] == "text" else {"input": {}}
        yield {"type": "content_block_start", "index": i, "content_block": {**block, **value}}
        delta = ({"type": "text_delta", "text": block["text"]} if block["type"] == "text" else
                 {"type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)})
        yield {"type": "content_block_delta", "index": i, "delta": delta}
        yield {"type": "content_block_stop", "index": i}
    yield {"type": "message_delta", "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
           "usage": {"output_tokens": message["usage"]["output_tokens"]}}
    yield {"type": "message_stop"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Gateway:
    def __init__(self, key, run: Path, limit=1500, *, allowed=OFFICE_TOOLS, private_markers=(), model=MODEL, url=URL):
        self.allowed = frozenset(allowed)
        self.private_markers = tuple(private_markers)
        self.token = secrets.token_hex(32)
        self.turn, self.count, self.limit = 0, 0, limit
        self.budget_exhausted = False
        self.reasoning = {}
        self.trace = run / "trace"
        self.lock = threading.Lock()
        self.model, self.url = model, url
        handlers = [NoRedirect()]
        if url.startswith("http://"):
            handlers.append(urllib.request.ProxyHandler({}))
        self.opener = urllib.request.build_opener(*handlers)
        self.key = key
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def handler(self):
        gw = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, code, data, mime="application/json"):
                if not isinstance(data, bytes):
                    data = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if not hmac.compare_digest(self.headers.get("x-api-key", ""), gw.token):
                    self.respond(401, {"error": {"type": "authentication_error", "message": "Invalid local credential"}})
                    return
                path = self.path.split("?")[0]
                query = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if path == "/v1/messages/count_tokens":
                    self.respond(200, {"input_tokens": max(1, len(json.dumps(query, ensure_ascii=False).encode()) // 3)})
                    return
                if path != "/v1/messages":
                    self.respond(404, {})
                    return
                with gw.lock:
                    if gw.count >= gw.limit:
                        gw.budget_exhausted = True
                        self.respond(400, {"type":"error", "error":{"type":"invalid_request_error","message":"Run request budget exhausted"}})
                        return
                    gw.count += 1
                    n, turn = gw.count, gw.turn
                prefix = gw.trace / f"api-{n:04}"
                record = {"n": n, "turn": turn, "start": time.time()}
                try:
                    payload = translate(query, gw.reasoning, gw.allowed, model=gw.model)
                    wire = json.dumps(payload, ensure_ascii=False)
                    if any(marker in wire for marker in (str(gw.trace.parent.resolve()), str(Path(__file__).resolve().parent), *gw.private_markers)):
                        raise ValueError("Private deployment path in model input")
                    record["request"] = payload
                    prefix.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False))
                    req = urllib.request.Request(gw.url, data=wire.encode(),
                            headers={"Authorization":"Bearer "+gw.key, "Content-Type":"application/json"})
                    with gw.opener.open(req, timeout=180) as resp:
                        record["upstream_status"] = resp.status
                        record["status"] = resp.status
                        record["request_id"] = resp.headers.get("x-request-id") or resp.headers.get("x-tt-logid")
                        reply = json.load(resp)
                    record["response"] = reply
                    message = anthropic(reply, gw.reasoning)
                    record["end"] = time.time()
                    prefix.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False))
                    if query.get("stream"):
                        stream = "".join("event: "+e["type"]+"\ndata: "+json.dumps(e,ensure_ascii=False)+"\n\n" for e in stream_events(message))
                        self.respond(200, stream.encode(), "text/event-stream")
                    else:
                        self.respond(200, message)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    status = getattr(exc, "code", 502)
                    detail = exc.read(1000).decode(errors="replace") if isinstance(exc, urllib.error.HTTPError) else str(exc)
                    detail = detail.replace(gw.key, "[redacted]")
                    record.update(end=time.time(), error=detail, status=status)
                    prefix.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False))
                    with contextlib.suppress(OSError):
                        self.respond(status, {"type": "error", "error": {"type": "api_error", "message": detail}})
        return Handler

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
