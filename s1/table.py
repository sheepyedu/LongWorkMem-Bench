"""Private transactional game store and public, game-only MCP stdio service."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from .game import act, observe


TOOLS = [
    {"name": "observe", "description": "查看牌桌、库存、当前可办事项及操作示例。查看不消耗行动。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "act", "description": "执行一次赛场操作。action 内使用 observe 所列的 op 和参数名；锁定和出牌立即生效。",
     "inputSchema": {"type": "object", "properties": {"action": {"type": "object",
                     "properties": {"op": {"type": "string"}}, "required": ["op"],
                     "additionalProperties": True}}, "required": ["action"], "additionalProperties": False}},
]
ALLOWED = frozenset("mcp__table__" + spec["name"] for spec in TOOLS)


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def connect(run):
    # Only a host-initialized run may be opened. A stale MCP process cannot create one.
    return sqlite3.connect((Path(run) / "table.sqlite").resolve().as_uri() + "?mode=rw",
                           uri=True, timeout=20)


def prepare(run, state):
    (run / "arena").mkdir(mode=0o700)
    with closing(sqlite3.connect(run / "arena" / "table.sqlite")) as conn, conn:
        conn.execute("CREATE TABLE game (turn INTEGER NOT NULL, state TEXT NOT NULL)")
        conn.execute("INSERT INTO game VALUES(0, ?)", (encode(state),))
        conn.execute("""CREATE TABLE calls (
            n INTEGER PRIMARY KEY, turn INTEGER NOT NULL, tool TEXT NOT NULL,
            args TEXT NOT NULL, result TEXT NOT NULL, process TEXT NOT NULL, request_id TEXT NOT NULL,
            UNIQUE(process, request_id))""")


def release(run, turn, state):
    with closing(connect(run / "arena")) as conn, conn:
        conn.execute("UPDATE game SET turn=?, state=?", (turn, encode(state)))


def snapshot(run, turn):
    # Close the action window and read the state in the same transaction.
    with closing(connect(run / "arena")) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT turn, state FROM game").fetchone()
        if row[0] != turn:
            raise RuntimeError("No active table for this turn")
        conn.execute("UPDATE game SET turn=0")
        state = json.loads(row[1])
        rows = conn.execute("SELECT n, tool, args, result FROM calls WHERE turn=? ORDER BY n", (turn,))
        with (run / "trace" / f"tools-{turn}.jsonl").open("x", encoding="utf8") as trace:
            for n, tool, args, result in rows:
                trace.write(encode(dict(n=n, turn=turn, tool=tool, args=json.loads(args),
                                        result=json.loads(result))) + "\n")
    return state


def game_call(run, turn, name, args, process, request_id):
    with closing(connect(run)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        identity = (process, encode(request_id))
        old = conn.execute("SELECT tool,args,result FROM calls WHERE process=? AND request_id=?", identity).fetchone()
        if old:
            if (name, encode(args)) != old[:2]:
                return {"ok": False, "error": "该操作编号已经使用。"}
            return json.loads(old[2])
        active, raw = conn.execute("SELECT turn,state FROM game").fetchone()
        state = json.loads(raw)
        if active != turn:
            result = {"ok": False, "error": "本阶段已结束。"}
        elif name == "observe" and args == {}:
            result = observe(state)
        elif (name == "act" and isinstance(args, dict) and set(args) == {"action"}
              and isinstance(args["action"], dict) and isinstance(args["action"].get("op"), str)
              and len(encode(args)) <= 32_768):
            result = act(state, args["action"])
            if result.get("ok") is True:
                conn.execute("UPDATE game SET state=?", (encode(state),))
        else:
            result = {"ok": False, "error": "未知赛场操作或参数不符。请先查看牌桌。"}
        conn.execute("INSERT INTO calls(turn,tool,args,result,process,request_id) VALUES(?,?,?,?,?,?)",
                     (turn, name, encode(args), encode(result), *identity))
        return result


def serve(run, turn, source=sys.stdin, sink=sys.stdout):
    process = uuid.uuid4().hex
    for line in source:
        request_id = None
        try:
            msg = json.loads(line)
            if not isinstance(msg, dict) or "id" not in msg:
                continue
            request_id = msg["id"]
            method = msg.get("method")
            if method == "initialize":
                result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                          "serverInfo": {"name": "table", "version": "1.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = msg["params"]
                if not isinstance(params.get("name"), str):
                    raise ValueError("Invalid tool name")
                val = game_call(run, turn, params["name"], params.get("arguments", {}), process, request_id)
                result = {"content": [{"type": "text", "text": encode(val)}], "isError": val.get("ok") is False}
            elif method == "ping":
                result = {}
            else:
                sink.write(encode({"jsonrpc": "2.0", "id": request_id,
                                   "error": {"code": -32601, "message": "Method not found"}}) + "\n")
                sink.flush()
                continue
            reply = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (ValueError, TypeError, KeyError, AttributeError):
            reply = {"jsonrpc": "2.0", "id": request_id,
                     "error": {"code": -32602, "message": "Invalid parameters"}}
        except Exception:
            # A host/storage failure must stop this MCP process. Never forward paths from exceptions.
            print("Table service unavailable", file=sys.stderr)
            raise SystemExit(1) from None
        sink.write(encode(reply) + "\n")
        sink.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("turn", type=int)
    options = parser.parse_args()
    serve(options.run, options.turn)
