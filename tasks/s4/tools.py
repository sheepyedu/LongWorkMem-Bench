"""MCP front end and loopback allowlist. The model only reaches player operations."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import contextmanager
import hmac
import json
import re
import secrets
import sys
import threading
from urllib.request import Request, urlopen


def spec(name, description, properties, required=()):
    return {"name":name,"description":description,"inputSchema":{
        "type":"object","properties":properties,"required":list(required),"additionalProperties":False}}


STR = {"type":"string"}
NUM = {"type":"integer"}
DECK = {"type":"object"}
TOOLS = [
    spec("look","Read current state. board=true includes the full map. after=N pages events following N.",
         {"board":{"type":"boolean"},"after":NUM}),
    spec("act","Use a current legal choice ID, or propose a trade using give and take resource objects.",
         {"position":NUM,"choice":NUM,"give":DECK,"take":DECK},("position",)),
    spec("notes","List, read, write or delete your own between-game notes.",
         {"op":{"type":"string","enum":["list","read","write","delete"]},"name":STR,"text":STR},("op",)),
]
ALLOWED = frozenset("mcp__table__"+tool["name"] for tool in TOOLS)


def integer(value):
    if isinstance(value,str) and re.fullmatch(r"[0-9]{1,7}",value):
        return int(value)
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer")
    return value


class Table:
    def __init__(self, engine, journal, note_file):
        self.engine, self.journal, self.note_file = engine, journal, note_file
        self.notes = {}
        self.goal = None
        self.table = None
        self.seq = 0
        self.lock = threading.Lock()

    def request(self, op, **args):
        packet = self.engine(op,**args)
        if "error" in packet:
            raise ValueError(packet["error"])
        return packet["result"]

    def open(self, name):
        state = self.request("open",name=name)["state"]
        self.table, self.first_position = name, state["position"]
        self.state = state
        self.set_goal(1)
        return state

    def set_goal(self, n):
        self.goal = self.state["completed_own_turns"]+n

    def done(self):
        return bool(self.state["finished"]) or self.state["completed_own_turns"] >= self.goal

    def memory(self, op, name=None, text=None):
        if op == "list":
            if name is not None or text is not None:
                raise ValueError("List takes no name or text")
            return {"files":sorted(self.notes)}
        if not isinstance(name,str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,60}", name) or name in (".",".."):
            raise ValueError("Use a simple note name without directories")
        if op in ("read","delete") and text is None:
            if name not in self.notes:
                return {"error":"note_not_found"}
            if op == "read":
                return {"name":name,"text":self.notes[name]}
            del self.notes[name]
        elif op == "write" and isinstance(text,str):
            # Tool transport guard, not a limit on how many characters can be remembered across files.
            if len(text.encode()) > 24_000:
                raise ValueError("Split notes above 24000 bytes into multiple files")
            self.notes[name] = text
        else:
            raise ValueError("Invalid note operation")
        tmp = self.note_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.notes,ensure_ascii=False,indent=2))
        tmp.replace(self.note_file)
        return {"ok":True,"name":name}

    def dispatch(self, name, args):
        with self.lock:
            try:
                if not isinstance(args,dict):
                    raise ValueError("Expected an object")
                if name == "look":
                    parsed = dict(args)
                    if "board" in parsed and type(parsed["board"]) is not bool:
                        raise ValueError("board must be a boolean")
                    if "after" in parsed:
                        parsed["after"] = max(integer(parsed["after"]), self.first_position)
                    result = {"state":self.request("view",**parsed),"legal":self.request("legal"),
                              "segment_done":self.done()}
                elif name == "act":
                    if self.done():
                        raise ValueError("Segment finished; wait for the next user message")
                    parsed = dict(args)
                    parsed["position"] = integer(parsed.get("position"))
                    if "choice" in parsed:
                        parsed["choice"] = integer(parsed["choice"])
                    for k in ("give","take"):
                        if isinstance(parsed.get(k),dict):
                            parsed[k] = {resource:integer(n) for resource,n in parsed[k].items()}
                    result = self.request("act",**parsed)
                    self.state = result["state"]
                    result["segment_done"] = self.done()
                elif name == "notes":
                    result = self.memory(**args)
                else:
                    raise ValueError("Unknown tool")
            except (TypeError,ValueError) as exc:
                result = {"error":str(exc)}
            self.seq += 1
            with self.journal.open("a") as stream:
                print(json.dumps({"seq":self.seq,"table":self.table,"tool":name,"args":args,
                                  "result":result},ensure_ascii=False),file=stream)
            return result


@contextmanager
def broker(table):
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("Authorization",""),token):
                self.send_error(403)
                return
            try:
                n = int(self.headers["Content-Length"])
                if not 0 < n <= 64_000:
                    raise ValueError("Invalid body size")
                name,args = json.loads(self.rfile.read(n))
                result = table.dispatch(name,args)
            except (TypeError,ValueError,KeyError):
                self.send_error(400)
                return
            raw = json.dumps(result,ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Length",str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    with ThreadingHTTPServer(("127.0.0.1",0),Handler) as server:
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            yield "http://127.0.0.1:"+str(server.server_port),token
        finally:
            server.shutdown()
            thread.join()


def serve(url, token):
    for line in sys.stdin:
        req = json.loads(line)
        if "id" not in req:
            continue
        ident, meth = req["id"], req["method"]
        if meth == "initialize":
            value = {"protocolVersion":req["params"]["protocolVersion"],
                     "capabilities":{"tools":{}},"serverInfo":{"name":"table","version":"1"}}
        elif meth == "tools/list":
            value = {"tools":TOOLS}
        elif meth == "tools/call":
            p = req["params"]
            data = json.dumps([p["name"],p.get("arguments",{})]).encode()
            with urlopen(Request(url,data=data,headers={"Authorization":token}),timeout=45) as response:
                value = {"content":[{"type":"text","text":response.read().decode()}]}
        elif meth == "ping":
            value = {}
        else:
            print(json.dumps({"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":"Unknown method"}}),flush=True)
            continue
        print(json.dumps({"jsonrpc":"2.0","id":ident,"result":value}),flush=True)


if __name__ == "__main__":
    serve(*sys.argv[1:])
