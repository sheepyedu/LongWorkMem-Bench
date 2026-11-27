"""Run persistent service maintenance sessions with Claude Code and Ark."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from tasks.protocol import PROTOCOL, PUBLIC_SEED, PUBLIC_VARIANT

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from tasks.w1.claude import run_claude
from tasks.w1.gateway import Gateway, MODEL, URL
from . import sandbox
from .runstate import freeze

ALLOWED = {"mcp__workshop__shell"}
CONTEXT = ("你是客服平台的开发维护工程师。通过 workshop 的 shell 在交接的同一份本地工作区完成各次委托。"
           "可用 python3 和标准库 SQLite；计时可用 Python 的 time 模块。长输出可存入 scratch/ 分段读取。input 放来件，project 放源程序，data 放业务数据库，out 放交付，"
           "notes 和 scratch 可自行使用。可以编写测试、维护工作笔记，按业务入口核实结果。每次结束时简报实际完成及遗留事项。")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    staged = path.with_suffix(".partial")
    staged.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    staged.replace(path)


@contextmanager
def checkout(run, backend):
    if backend == "docker":
        (run / "work").mkdir()
        yield run / "work"
    else:
        with tempfile.TemporaryDirectory(prefix="workshop-") as tmp:
            work = Path(tmp).resolve() / "workspace"
            work.mkdir()
            try:
                yield work
            finally:
                shutil.move(str(work), run / "work")


def check_boundary(work, backend):
    marker = work / "input" / ".connection"
    marker.write_text("service")
    private = str(Path(__file__).resolve())
    probe = """python3 - <<'PY'
from pathlib import Path
import socket, os, sqlite3
assert Path.cwd().name == 'workspace'
assert Path('input/.connection').read_text() == 'service'
assert not any(k in os.environ for k in ('ARK_API_KEY', 'ANTHROPIC_API_KEY'))
for action in (lambda: Path('input/.connection').write_text('bad'), lambda: Path(PRIVATE).read_bytes(),
               lambda: socket.create_connection(('1.1.1.1', 443), timeout=1)):
    try: action()
    except OSError: pass
    else: raise AssertionError('unexpected access')
with sqlite3.connect('scratch/probe.db') as db:
    db.execute('create table t(n)')
print('workspace ready')
PY""".replace("PRIVATE", repr(private))
    try:
        result = sandbox.shell(work, probe, backend)
        if result["status"] or "workspace ready" not in result["output"]:
            raise RuntimeError("Workspace isolation check failed: " + str(result))
        return result
    finally:
        marker.unlink(missing_ok=True)
        (work / "scratch/probe.db").unlink(missing_ok=True)


def release_turn(work, turn, variant, seed, level, window, rotate):
    from . import settlement
    prompt = settlement.release(work, turn, variant, seed, level)
    if rotate and turn == 1:
        prompt += " 本周第5、7轮由新班组接手。班组仅交接工作文件和笔记；请保存后续结账所需的原始约定。"
    if rotate and turn in (5, 7):
        prompt = "新班组上岗。请根据工位的源码、交付和前班笔记接手。 " + prompt
    if window:
        prompt += (f" 客户在本轮第 {window} 次工作区 shell 调用结束时取件（若提前结束则当时取件）。"
                   "请安排好查阅和执行，可在一条命令内批处理。取件后仍可检查和补交轮末修复版。")
    if turn == 2:
        prompt += " 交接通知 handover.txt 仅本轮可阅；请自行保留后续所需的授权信息。"
    if turn == 3:
        (work / "input/handover.txt").unlink()
    return prompt


def run_session(run, variant, backend, key, *, limit=None, model=MODEL, url=URL, level=3, seed=PUBLIC_SEED, window=None, rotate=True):
    run = Path(run).resolve()
    run.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name in ("trace", "snapshots"):
        (run / name).mkdir()
    session = str(uuid.uuid4())
    package = Path(__file__).resolve().parent
    files = [p for p in package.rglob("*.py") if p.relative_to(package).parts[0] != "tests" and "__pycache__" not in p.parts]
    files.extend(package.parent / "w1" / name for name in ("claude.py", "gateway.py", "office.py"))
    manifest = {"mode": "settlement", "variant": variant, "backend": backend, "model": model, "session": session,
                "start": timestamp(), "limit": limit, "turns": [], "status": "running",
                "claude": subprocess.check_output(["claude", "--version"], text=True).strip(),
                "git": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=package, text=True).strip(),
                "source_hashes": {str(p.relative_to(package.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    manifest.update(protocol=PROTOCOL, withdraw_handover=True, level=level, seed=seed, endpoint=url,
                    dispatch_window=window, rotation_turns=[5, 7] if rotate else [],
                    condition="public" if (seed == PUBLIC_SEED and variant == PUBLIC_VARIANT and rotate
                                           and not window and limit is None and backend == "docker") else "experiment")
    if backend == "docker":
        manifest["image"] = sandbox.image_id()
    def save():
        write_json(run / "manifest.json", manifest)
    save()
    try:
        with checkout(run, backend) as work:
            for name in ("input", *sandbox.WRITABLE):
                (work / name).mkdir(exist_ok=True)
            manifest["isolation"] = check_boundary(work, backend)
            turns = range(1, 8)
            env = {"PYTHONPATH": str(package.parents[1])}
            for name in ("DOCKER_HOST", "DOCKER_CONTEXT"):
                if os.getenv(name):
                    env[name] = os.environ[name]
            if backend == "docker":
                env["C1_IMAGE"] = manifest["image"]
            with tempfile.TemporaryDirectory(prefix="service-client-") as tmp, Gateway(
                    key, run, limit, allowed=ALLOWED, model=model, url=url, private_markers=(str(package), "c1-grade/", ".claude-manager/worktrees/")) as gateway:
                client = Path(tmp)
                (client / "desk").mkdir()
                for index, turn in enumerate(turns):
                    new_shift = rotate and turn in manifest["rotation_turns"]
                    if new_shift:
                        session = str(uuid.uuid4())
                        client = Path(tmp) / f"shift-{turn}"
                        (client / "desk").mkdir(parents=True)
                        gateway.reasoning.clear()
                    prompt = release_turn(work, turn, variant, seed, level, window, rotate)
                    (run / "trace" / f"prompt-{turn}.txt").write_text(prompt)
                    config = {"mcpServers": {"workshop": {"command": sys.executable, "args": [
                        "-m", "tasks.c1.sandbox", str(work), backend, str(run / "trace" / f"tools-{turn}.jsonl")], "env": env}}}
                    dispatch = run / "dispatch" / str(turn)
                    if window:
                        config["mcpServers"]["workshop"]["args"].extend([str(dispatch), str(window)])
                    try:
                        n = run_claude(run, turn, gateway, session, prompt, client, config=config,
                                       context=CONTEXT, allowed=ALLOWED, first_session=index == 0 or new_shift)
                    except Exception:
                        freeze(work, run / "partial" / str(turn))
                        manifest["budget_exhausted"] = gateway.budget_exhausted
                        raise
                    if window and not dispatch.exists():
                        journal = run / "trace" / f"tools-{turn}.jsonl"
                        if journal.exists() and len(journal.read_bytes().splitlines()) >= window:
                            raise RuntimeError("Missing customer dispatch at the scheduled command")
                        freeze(work, dispatch)
                    omissions = freeze(work, run / "snapshots" / str(turn))
                    manifest["turns"].append({"turn": turn, "session": session, "upstream_calls": n, "end": timestamp(), "omissions": omissions})
                    save()
                    print(f"{run.name} turn {turn} completed ({n} upstream calls)", flush=True)
        manifest["status"] = "complete"
    except Exception as exc:
        manifest["status"] = "budget_exhausted" if manifest.get("budget_exhausted") else "error"
        manifest["error"] = str(exc)
        raise
    finally:
        manifest["end"] = timestamp()
        save()
    return manifest
