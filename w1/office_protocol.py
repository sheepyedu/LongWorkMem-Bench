"""MCP stdio service for the shared office tools."""
import json
from pathlib import Path
import sys

from .mail import act
from .office import TOOLS


def serve(run: Path, turn: int, backend: str, execute_shell) -> None:
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        response = {"jsonrpc": "2.0", "id": request["id"]}
        method = request.get("method")
        try:
            if method == "initialize":
                result = {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}},
                          "serverInfo": {"name": "office", "version": "1.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = request["params"]
                name, args = params["name"], params["arguments"]
                if name == "shell":
                    value = execute_shell(run, turn, request["id"], args["command"], backend)
                elif name in ("draft", "deliver"):
                    value = {"receipt": act(run, turn, name, **args)}
                else:
                    raise ValueError("Unknown business tool")
                result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
            elif method == "ping":
                result = {}
            else:
                response["error"] = {"code": -32601, "message": "Method not found"}
                result = None
            if result is not None:
                response["result"] = result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail = exc.strerror if isinstance(exc, OSError) else str(exc)
            response["result"] = {"isError": True, "content": [{"type": "text", "text": detail}]}
        print(json.dumps(response, ensure_ascii=False), flush=True)
