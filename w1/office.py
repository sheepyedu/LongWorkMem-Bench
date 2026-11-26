"""Three business tools exposed to Claude Code over MCP stdio.

The host service never executes agent commands directly. The shell sees a
read-only office and three writable folders, with no upstream credentials.
"""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from .mail import act

IMAGE = "longworkmem-office:1"
WRITABLE = ("out", "notes", "scratch")
SHELL_TIMEOUT = 60


def shell(work: Path, command: str, backend: str) -> dict:
    if not isinstance(command, str) or not command or len(command) > 100_000:
        raise ValueError("Expected a shell command up to 100,000 characters")
    work = work.resolve(strict=True)
    if any((work / name).is_symlink() for name in WRITABLE):
        raise ValueError("Invalid writable directory")
    if backend == "docker":
        argv = ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "96", "--memory", "640m",
                "--user", f"{os.getuid()}:{os.getgid()}", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
                "-e", "HOME=/office/notes", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-v", f"{work}:/office:ro", "-w", "/office"]
        for name in WRITABLE:
            argv.extend(["-v", f"{work / name}:/office/{name}:rw"])
        argv.extend([IMAGE, "/bin/sh", "-c", command])
        environment = os.environ.copy()
    elif backend == "seatbelt" and platform.system() == "Darwin":
        literal = json.dumps
        roots = ["/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/lib", "/usr/share", "/System",
                 "/Library/Apple", "/private/var/select", "/private/etc/apache2/mime.types", str(Path(sys.base_prefix).resolve()), str(Path(sys.prefix).resolve()), str(work)]
        roots = sorted(set(roots))
        rules = ["(version 1)", "(deny default)", '(import "system.sb")', "(allow process-exec process-fork)",
                 "(allow sysctl-read)", "(allow file-read-metadata)",
                 '(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
                 '(allow file-write* (literal "/dev/null"))',
                 '(allow mach-lookup (global-name "com.apple.system.logger") (global-name "com.apple.system.opendirectoryd.libinfo"))',
                 "(allow file-read* " + " ".join("(subpath " + literal(p) + ")" for p in roots) + ")",
                 "(allow file-write* " + " ".join("(subpath " + literal(str(work / x)) + ")" for x in WRITABLE) + ")"]
        argv = ["/usr/bin/sandbox-exec", "-p", "\n".join(rules), "/bin/zsh", "-f", "-c", command]
        environment = {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin:/usr/sbin",
                       "HOME": str(work / "notes"), "TMPDIR": str(work / "scratch"),
                       "TMPPREFIX": str(work / "scratch/sh"), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    else:
        raise ValueError("Select docker, or seatbelt on macOS")
    with tempfile.TemporaryFile() as output:
        import signal
        proc = subprocess.Popen(argv, cwd=work, stdout=output, stderr=subprocess.STDOUT, env=environment,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            status = proc.wait(timeout=SHELL_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            status = 124
        length = output.tell()
        output.seek(0)
        content = output.read(24_000).decode(errors="replace")
    if length > 24_000:
        content += "\n[Output truncated. Use a narrower search.]"
    return {"status": status, "output": content}


def tool(name, description, entries):
    return {"name": name, "description": description, "inputSchema": {"type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in entries.items()},
            "required": list(entries), "additionalProperties": False}}


TOOLS = [tool("shell", "在部门共享盘根目录执行 shell 命令。可用 python3 和 openpyxl，读取 input/、inbox/，写 out/、notes/、scratch/。每次命令独立启动，文件保留。", {"command": "shell command"}),
         *[tool(name, desc, {"recipient": "一个内部邮箱", "attachment": "相对路径 out/...", "subject": "邮件主题"})
           for name, desc in [("draft", "保存带附件的内部邮件草稿，返回草稿编号。"),
                              ("deliver", "实际投递内部邮件并返回回执号，每次调用即产生一封邮件。")]]]


def serve(run: Path, turn: int, backend: str) -> None:
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
                    value = shell(run / "work", args["command"], backend)
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


if __name__ == "__main__":
    serve(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
