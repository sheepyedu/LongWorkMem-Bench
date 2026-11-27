"""One isolated Claude Code user turn, shared by text-tool game and office sessions."""
import json
import os
import shutil
import subprocess


def run_claude(run, turn, gw, session, prompt, client, *, config, context, allowed, first_session):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code executable missing")
    env = {"PATH": os.environ["PATH"], "HOME": str(client), "CLAUDE_CONFIG_DIR": str(client/"config"),
           "ANTHROPIC_BASE_URL": gw.base, "ANTHROPIC_API_KEY": gw.token,
           "ANTHROPIC_MODEL": gw.model, "ANTHROPIC_SMALL_FAST_MODEL": gw.model,
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1",
           "DISABLE_ERROR_REPORTING":"1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY":"1",
           "CLAUDE_CODE_ATTRIBUTION_HEADER":"0", "ENABLE_TOOL_SEARCH":"false",
           "NO_PROXY":"127.0.0.1,localhost", "LANG": "en_US.UTF-8"}
    argv = [exe, "-p", "--bare", "--model", gw.model, "--strict-mcp-config", "--mcp-config", json.dumps(config),
            "--settings", "{}", "--setting-sources", "", "--tools", "", "--permission-mode", "dontAsk",
            "--allowedTools", ",".join(sorted(allowed)),
            "--disable-slash-commands", "--system-prompt", context, "--output-format", "stream-json", "--verbose",
            "--session-id" if first_session else "--resume", session]
    gw.turn = turn
    start = gw.count
    stdout = run / "trace" / f"turn-{turn}.jsonl"
    with stdout.open("x") as out, (run/"trace"/f"turn-{turn}.stderr").open("x") as err:
        proc = subprocess.run(argv, cwd=client/"desk", env=env, input=prompt, text=True, stdout=out, stderr=err)
    result = None
    with stdout.open() as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("type") == "result":
                result = event
    if proc.returncode or not result or result.get("is_error") or gw.count == start:
        message = str(result.get("result",""))[:550] if result else "missing result"
        raise RuntimeError(f"turn {turn} harness failed (exit {proc.returncode}, {gw.count-start} upstream calls): {message}")
    return gw.count-start
