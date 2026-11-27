"""One MCP shell in a persistent, network-isolated engineering checkout."""
import json
import os
from pathlib import Path
import subprocess
import sys

from tasks.w1.office import shell as isolated_shell, tool

WRITABLE = ("project", "data", "out", "scratch", "notes")
IMAGE = "python:3.12-slim"
TOOL = tool("shell", "在工单维护工作区执行 shell。可以使用 python3、sqlite3 Python 模块及标准命令，"
            "读 input/，修改 project/、data/、out/、notes/、scratch/。文件跨命令和委托保留。", {"command": "shell command"})


def image_id():
    return subprocess.check_output(["docker", "image", "inspect", os.getenv("C1_IMAGE", IMAGE),
                                    "--format", "{{.Id}}"], text=True).strip()


def shell(work, command, backend="seatbelt", timeout=60, *, image=None):
    # Homebrew's Python extension loads SQLite through its opt symlink.
    sqlite_lib = Path("/opt/homebrew/opt/sqlite/lib")
    libraries = (str(sqlite_lib), str(sqlite_lib.resolve())) if backend == "seatbelt" and sqlite_lib.exists() else ()
    return isolated_shell(Path(work), command, backend, writable=WRITABLE, timeout=timeout,
                          image=image or os.getenv("C1_IMAGE", IMAGE), mount="/workspace", check_runtime=True, runtime_roots=libraries)


def serve(work, backend, journal=None, dispatch=None, window=None):
    from .runstate import freeze
    calls = len(journal.read_bytes().splitlines()) if dispatch and journal.exists() else 0
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        reply = {"jsonrpc": "2.0", "id": request["id"]}
        method = request.get("method")
        try:
            if method == "initialize":
                reply["result"] = {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}},
                                   "serverInfo": {"name": "workshop", "version": "1"}}
            elif method == "tools/list":
                reply["result"] = {"tools": [TOOL]}
            elif method == "tools/call":
                params = request["params"]
                if params["name"] != "shell":
                    raise ValueError("Unknown workshop tool")
                value = shell(work, params["arguments"]["command"], backend)
                if journal is not None:
                    with journal.open("a") as log:
                        print(json.dumps({"tool": "shell", "args": params["arguments"], "result": value}, ensure_ascii=False), file=log)
                if dispatch:
                    calls += 1
                    if calls == window:
                        freeze(work, dispatch)
                reply["result"] = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
            elif method == "ping":
                reply["result"] = {}
            else:
                reply["error"] = {"code": -32601, "message": "Method not found"}
        except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            # Host deployment details belong in the controller log.
            print(str(exc), file=sys.stderr, flush=True)
            reply["result"] = {"isError": True, "content": [{"type": "text", "text": "无法执行本次工作区命令。"}]}
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    serve(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]) if len(sys.argv) > 3 else None,
          Path(sys.argv[4]) if len(sys.argv) > 4 else None, int(sys.argv[5]) if len(sys.argv) > 5 else None)
