"""Run the eight-turn card league or a fresh, paired registration control."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import sys
import tempfile
import uuid

from w1.claude import run_claude
from w1.gateway import Gateway, MODEL
from .game import new_game, open_turn, scout_notice
from .table import ALLOWED, prepare, release, snapshot

CONTEXT = ("你是参加联赛的牌队领队。通过 table 的 observe 查看桌面、业务规则和操作示例，"
           "通过 act 实际操作牌桌及管理队伍。可使用赛季笔记。完成每次委托后简要汇报实际结果和待办。")
CONTROL = ("请按当前桌面为统一器材组选择装备并锁定报名，尽量让两手合计达到比赛门槛。"
           "自由组沿用当前默认草案，两份报名一起提交。")
IMAGE = "longworkmem-table:1"
SOURCE = Path(__file__).resolve().parents[1]
PRIVATE_MARKERS = ("s1/grade.py", "s1.grade", "test_s1_grade", "snapshots/7.json", ".claude-manager/worktrees/")
ROUNDS = range(1, 9)


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def source_hashes():
    files = [*sorted((SOURCE / "s1").glob("*.py")), SOURCE / "w1/claude.py", SOURCE / "w1/gateway.py"]
    return {str(f.relative_to(SOURCE)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def docker_image(tag):
    image = subprocess.check_output(["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                                    text=True).strip()
    files = ("__init__.py", "game.py", "table.py")
    program = ("from pathlib import Path; import hashlib, json, s1, sys; "
               "root = Path(s1.__file__).parent; "
               "print(json.dumps([hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sys.argv[1:]]))")
    actual = json.loads(subprocess.check_output(["docker", "run", "--rm", "--pull=never", "--network=none",
                        "--read-only", "--cap-drop=ALL", "--entrypoint", "python", image, "-c", program, *files],
                        text=True))
    expected = [hashlib.sha256((SOURCE / "s1" / name).read_bytes()).hexdigest() for name in files]
    if actual != expected:
        raise RuntimeError("Table image differs from host rules; rebuild the game image before running")
    return image


def config_for(run, turn, image):
    if image:
        args = ["run", "--rm", "-i", "--init", "--pull=never", "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=32",
                "--memory=160m", "--user", f"{os.getuid()}:{os.getgid()}",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=8m",
                "--mount", f"type=bind,src={run.resolve() / 'arena'},dst=/arena", image, "/arena", str(turn)]
        # claude's isolated HOME has no Docker config. Parent supplies the daemon socket if necessary.
        client_env = {name: os.environ[name] for name in ("DOCKER_HOST",) if name in os.environ}
        command = {"command": "docker", "args": args, "env": client_env}
    else:
        command = {"command": sys.executable, "args": ["-m", "s1.table", str(run.resolve() / "arena"), str(turn)],
                   "env": {"PYTHONPATH": str(SOURCE)}}
    return {"mcpServers": {"table": command}}



def table_preflight(run, image, client):
    """Open a disposable game through the exact MCP launch command and mount."""
    with tempfile.TemporaryDirectory(dir=run, prefix="preflight-") as tmp:
        probe = Path(tmp)
        game = new_game("A", 0)
        prepare(probe, game)
        open_turn(game, 1)
        release(probe, 1, game)
        cfg = config_for(probe, 1, image)["mcpServers"]["table"]
        marker = secrets.token_hex(10)
        calls = [
            ("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}),
            ("tools/list", {}),
            ("resources/list", {}),
            ("tools/call", {"name": "observe", "arguments": {}}),
            ("tools/call", {"name": "act", "arguments": {"action":{"op":"note","text":marker}}}),
            ("tools/call", {"name": "act", "arguments": {"action":{"op":"read_note"}}}),
        ]
        wire = "".join(json.dumps({"jsonrpc":"2.0","id":n,"method":method,"params":args}) + "\n"
                       for n, (method, args) in enumerate(calls, start=1))
        env = {"PATH": os.environ["PATH"], "HOME": str(client), "LANG": "en_US.UTF-8", **cfg["env"]}
        proc = subprocess.run([cfg["command"], *cfg["args"]], cwd=client / "desk", env=env, input=wire,
                              capture_output=True, text=True, timeout=50)
        if proc.returncode:
            raise RuntimeError("MCP preflight failed to open the disposable table: " + proc.stderr[-450:])
        msgs = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        if len(msgs) != len(calls) or [m.get("id") for m in msgs] != list(range(1, 7)):
            raise RuntimeError("MCP preflight returned an incomplete protocol transcript")
        names = {t["name"] for t in msgs[1]["result"]["tools"]}
        results = [json.loads(m["result"]["content"][0]["text"]) for m in msgs[3:]]
        if (msgs[0]["result"]["capabilities"] != {"tools": {}} or names != {"observe", "act"}
                or msgs[2].get("error", {}).get("code") != -32601 or "commands" not in results[0]
                or results[1].get("ok") is not True or results[2].get("note") != marker):
            raise RuntimeError("MCP preflight failed capability, isolation or write/read checks")
        return {"transport": "stdio", "tools": sorted(names), "resources": False,
                "observation": True, "note_roundtrip": True}


def verify_client(path):
    with path.open(encoding="utf-8") as stream:
        entries = [row for line in stream if (row := json.loads(line)).get("type") == "system"
                   and row.get("subtype") == "init"]
    if len(entries) != 1:
        raise RuntimeError("Claude Code did not report its active MCP tools")
    init = entries[0]
    servers = [(s.get("name"), s.get("status")) for s in init.get("mcp_servers", [])]
    if servers != [("table", "connected")] or set(init.get("tools", [])) != ALLOWED:
        raise RuntimeError("Claude Code did not connect exclusively to the expected table tools")


def play(run, variant, seed, credential, mode, limit, image=None):
    run = Path(run).resolve()
    run.mkdir(exist_ok=False, parents=True, mode=0o700)
    (run / "trace").mkdir()
    (run / "snapshots").mkdir()
    session = str(uuid.uuid4())
    manifest = {"variant": variant, "seed": seed, "mode": mode, "status": "running", "model": MODEL,
                "backend": "docker" if image else "native", "image_id": image, "session": session,
                "allowed_tools": sorted(ALLOWED), "start": now(), "limit": limit, "turns": [],
                "python": platform.python_version(), "source_hashes": source_hashes(),
                "git": subprocess.check_output(["git","rev-parse","HEAD"],cwd=SOURCE,text=True).strip(),
                "claude": subprocess.check_output(["claude","--version"], text=True).strip()}
    journal = run / "manifest.json"
    write(journal, manifest)
    try:
        state = new_game(variant, seed)
        prepare(run, state)
        cold = mode in ("current", "reminder")
        if cold:
            for t in range(1, 7):
                open_turn(state, t)
        turns = [7] if cold else [1] if mode == "smoke" else ROUNDS
        value = secrets.token_hex(8) if mode == "smoke" else None
        with (tempfile.TemporaryDirectory(prefix="league-client-") as tmp,
              Gateway(credential, run, limit, allowed=ALLOWED,
                      private_markers=(*PRIVATE_MARKERS, str(SOURCE), str(run))) as gateway):
            client = Path(tmp)
            (client / "desk").mkdir()
            manifest["mcp_preflight"] = table_preflight(run, image, client)
            write(journal, manifest)
            for index, turn in enumerate(turns):
                if gateway.count >= limit:
                    manifest["status"] = "budget_exhausted"
                    return
                before = gateway.count
                prompt = open_turn(state, turn)
                if cold:
                    prompt = CONTROL
                    if mode == "reminder":
                        prompt += "\n另附开幕侦察员当时的播报原文：" + scout_notice(variant)
                elif value:
                    prompt = (f"请实际查看牌桌，然后将以下交接代号完整写入赛季笔记：{value}。"
                              "写入后用赛场工具实际重新读取笔记，向我汇报读回的代号。")
                release(run, turn, state)
                (run / "trace" / f"prompt-{turn}.txt").write_text(prompt, encoding="utf8")
                try:
                    count = run_claude(run, turn, gateway, session, prompt, client,
                                      config=config_for(run, turn, image), context=CONTEXT,
                                      allowed=ALLOWED, first_session=index == 0)
                    verify_client(run / "trace" / f"turn-{turn}.jsonl")
                except RuntimeError:
                    if not gateway.budget_exhausted or mode == "smoke":
                        raise
                    verify_client(run / "trace" / f"turn-{turn}.jsonl")
                    manifest["turns"].append({"turn": turn, "upstream_calls": gateway.count - before,
                                              "end": "budget_exhausted"})
                    manifest["status"] = "budget_exhausted"
                    return
                finally:
                    state = snapshot(run, turn)
                    write(run / "snapshots" / f"{turn}.json", state)
                manifest["turns"].append({"turn": turn, "upstream_calls": count})
                write(journal, manifest)
                if value:
                    verify_smoke(run, value)
                print(f"{mode} {variant} turn {turn} complete ({count} upstream calls)", flush=True)
        manifest["status"] = "complete"
    except Exception as exc:
        manifest.update(status="error", error=str(exc).replace(credential, "[redacted]"))
        raise
    finally:
        manifest["end"] = now()
        write(journal, manifest)


def verify_smoke(run, value):
    calls = [json.loads(line) for line in (run / "trace/tools-1.jsonl").read_text().splitlines()]
    observed = any(c["tool"] == "observe" and c["result"].get("ok") is not False for c in calls)
    token = re.compile(r"(?<![a-zA-Z0-9_])" + re.escape(value) + r"(?![a-zA-Z0-9_])")
    written = None
    verified = False
    for call in sorted(calls, key=lambda row: row["n"]):
        if call["tool"] != "act" or call["result"].get("ok") is not True:
            continue
        action = call["args"].get("action", {})
        if action.get("op") == "note":
            written = action.get("text")
            verified = False
        elif (action.get("op") == "read_note" and isinstance(written, str)
              and token.search(written) and call["result"].get("note") == written):
            verified = True
    lines = [json.loads(line) for line in (run / "trace/turn-1.jsonl").read_text().splitlines()]
    confirmed = any(e.get("type") == "result" and not e.get("is_error")
                    and token.search(e.get("result", "")) for e in lines)
    if not (observed and verified and confirmed):
        raise RuntimeError("Smoke did not demonstrate observation, note persistence, readback and final receipt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--variants", nargs="+", choices=["A","B"], default=["A","B"])
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--backend", choices=["native","docker"], default="native")
    parser.add_argument("--image", default=IMAGE)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--control", choices=["current","reminder"])
    modes.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or len(set(args.variants)) != len(args.variants):
        parser.error("Use a positive budget and distinct variants")
    args.dest.mkdir(parents=True, exist_ok=True)
    if any((args.dest / v).exists() for v in args.variants):
        parser.error("Each variant requires a fresh run directory")
    image = None
    if args.backend == "docker":
        image = docker_image(args.image)
    credential = os.environ.get("ARK_API_KEY") or getpass.getpass("Ark credential (hidden): ")
    mode = args.control or ("smoke" if args.smoke else "natural")
    with ThreadPoolExecutor(max_workers=len(args.variants)) as pool:
        runs = [pool.submit(play, args.dest / v, v, args.seed, credential, mode, args.limit, image)
                for v in args.variants]
        for run in runs:
            run.result()


if __name__ == "__main__":
    main()
