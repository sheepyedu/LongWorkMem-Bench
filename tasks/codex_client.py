"""Native Codex app-server transport with an isolated client home and task-only tools."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


MODEL = "gpt-6.1-sol"


class Client:
    def __init__(self, run, model=MODEL, effort="low"):
        self.run = run
        self.model = model
        self.effort = effort
        self.sequence = 0
        self.thread = None

    def __enter__(self):
        self.stack = ExitStack()
        try:
            root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
            home = root / "client"
            home.mkdir()
            desk = root / "desk"
            desk.mkdir()
            self.desk = str(desk)
            source = Path(os.getenv("CODEX_HOME", Path.home() / ".codex"))
            # Only the CLI's login is shared. Never load the operator's hooks,
            # projects, instructions, plugins, or previously recorded conversations.
            if (source / "auth.json").is_file():
                (home / "auth.json").symlink_to(source / "auth.json")
            env = {k: v for k, v in os.environ.items() if k in (
                "PATH", "LANG", "TMPDIR", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY",
                "https_proxy", "http_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE")}
            env.update(CODEX_HOME=str(home), HOME=str(root))
            argv = [shutil.which("codex") or "codex", "app-server", "--stdio"]
            for feature in ("apps", "plugins", "hooks", "shell_tool", "multi_agent", "memories",
                            "computer_use", "browser_use", "in_app_browser", "image_generation",
                            "skill_search", "sleep_tool", "tool_suggest"):
                argv.extend(["--disable", feature])
            argv.extend(["--enable", "skip_host_skill_discovery", "-c", 'web_search="disabled"',
                         "-c", "project_doc_max_bytes=0"])
            err = self.stack.enter_context((self.run/"trace"/"codex.stderr").open("x"))
            self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                      text=True, encoding="utf8", cwd=desk, env=env)
            self.stack.callback(self.stop)
            self.rpc("initialize", {"clientInfo":{"name":"longworkmem","version":"1"},
                                    "capabilities":{"experimentalApi":True}})
            self.send({"method":"initialized"})
            return self
        except BaseException:
            self.stack.close()
            raise

    def stop(self):
        self.p.stdin.close()
        try:
            self.p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.p.terminate()
            self.p.wait(timeout=8)
        self.p.stdout.close()

    def __exit__(self, *exc):
        self.stack.close()

    def send(self, value):
        self.p.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def read(self):
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("Codex app-server closed its event stream")
        return json.loads(line)

    def rpc(self, method, params):
        self.sequence += 1
        self.send(dict(id=self.sequence, method=method, params=params))
        while True:
            msg = self.read()
            if msg.get("id") == self.sequence and "method" not in msg:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg["result"]
            if "id" in msg:
                raise RuntimeError(f"Unexpected server request during {method}: {msg.get('method')}")

    def start(self, context, specs):
        self.specs = {s["name"]:s for s in specs}
        config = dict(model=self.model, allowProviderModelFallback=False, cwd=self.desk,
                      environments=[], runtimeWorkspaceRoots=[], selectedCapabilityRoots=[],
                      approvalPolicy="never", sandbox="read-only", ephemeral=True,
                      baseInstructions=context, config={"model_reasoning_effort":self.effort},
                      dynamicTools=[{"type":"function", **s, "deferLoading":False} for s in specs])
        result = self.rpc("thread/start", config)
        if result["model"] != self.model or result["instructionSources"]:
            raise RuntimeError("Unexpected model or inherited project instructions")
        self.thread = result["thread"]["id"]
        with (self.run/"trace"/"threads.jsonl").open("a") as f:
            print(json.dumps(dict(thread=self.thread,model=result["model"],effort=result["reasoningEffort"],
                                  tools=list(self.specs),context=context),ensure_ascii=False),file=f)
        return self.thread

    def turn(self, idx, prompt, tool=None):
        trace = self.run/"trace"/f"turn-{idx}.jsonl"
        params = dict(threadId=self.thread, input=[dict(type="text",text=prompt)],
                      effort=self.effort, environments=[])
        answer = None
        usage = None
        with trace.open("x", buffering=1) as log:
            def record(direction, value):
                print(json.dumps({"direction":direction, "message":value}, ensure_ascii=False),file=log)
            self.sequence += 1
            request = dict(id=self.sequence,method="turn/start",params=params)
            record("send",request)
            self.send(request)
            while True:
                msg = self.read()
                record("recv",msg)
                method = msg.get("method")
                p = msg.get("params",{})
                if "error" in msg and not method:
                    raise RuntimeError(str(msg["error"]))
                if p.get("threadId",self.thread) != self.thread:
                    continue
                if method == "item/tool/call":
                    name = p["tool"]
                    if tool is None or name not in self.specs:
                        raise RuntimeError("Unexpected tool "+name)
                    try:
                        value = tool(name, p["arguments"])
                        output, success = json.dumps(value,ensure_ascii=False), True
                    except (ValueError,KeyError,TypeError,OSError) as exc:
                        output, success = str(exc), False
                    result = dict(id=msg["id"],result=dict(success=success, contentItems=[
                        dict(type="inputText",text=output)]))
                    record("send",result)
                    self.send(result)
                elif "id" in msg and method:
                    raise RuntimeError(f"Unexpected Codex server request: {method}")
                elif method == "item/completed":
                    item = p["item"]
                    if item["type"] == "agentMessage":
                        answer = item["text"]
                    elif item["type"] not in ("userMessage","reasoning","dynamicToolCall","contextCompaction",
                                              "plan","modelReroute"):
                        raise RuntimeError("Unexpected Codex item "+item["type"])
                    if item["type"] == "modelReroute":
                        raise RuntimeError("Model rerouted")
                elif method == "thread/tokenUsage/updated":
                    usage = p["tokenUsage"]["total"]
                elif method == "turn/completed":
                    turn = p["turn"]
                    if turn["status"] != "completed" or answer is None:
                        raise RuntimeError(f"Codex turn failed: {turn.get('error')}")
                    return answer, usage
