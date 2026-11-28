"""Eight-turn calendar maintenance trajectory in one native Claude Code session."""

import argparse
from contextlib import redirect_stderr
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from tasks.c1.runstate import freeze
from tasks.w1.claude import run_claude
from tasks.w1.gateway import Gateway, MODEL, URL
from tasks.w1.office import SHELL_TIMEOUT, shell, tool
from .scenario import setup, release, write, WRITABLE
from .subscriber import receipts, publish, interrupt

TOOLS = [
    tool(
        "shell",
        "在离线 Docker 工位执行 shell，可读资料并写工作目录。",
        {"command": "命令"},
    ),
    tool(
        "publish",
        "实际提交 ICS 给内部订阅端。",
        {"channel": "A 或 B", "key": "批次唯一重试键", "file": "out/ 下的 ICS"},
    ),
    tool("receipts", "查询频道的实际已收批次。", {"channel": "A 或 B"}),
]
ALLOWED = {"mcp__calendar__" + s["name"] for s in TOOLS}
CONTEXT = "你是排期门户维护工程师。使用 calendar 工具完成实际工作。工作区 project、data、notes、out、scratch 可写、跨委托持久。input 为只读资料。Docker 与宿主分离。完成每次委托时简报实际交付、验证及遗留事项。"


def execute(work, cmd, image, *, timeout=SHELL_TIMEOUT):
    return shell(
        work,
        cmd,
        "docker",
        writable=WRITABLE,
        image=image,
        mount="/workspace",
        check_runtime=True,
        timeout=timeout,
    )


def serve(run, t, image, edition=None):
    active_tools = edition.TOOLS if edition else TOOLS
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method = msg["method"]
        if method == "initialize":
            result = dict(
                protocolVersion=msg["params"]["protocolVersion"],
                capabilities={"tools": {}},
                serverInfo=dict(name="calendar", version="1"),
            )
        elif method == "tools/list":
            result = dict(tools=active_tools)
        elif method == "tools/call":
            p = msg["params"]
            args = p["arguments"]
            name = p["name"]
            try:
                contract = next(
                    (s["inputSchema"] for s in active_tools if s["name"] == name), None
                )
                if (
                    not contract
                    or set(args) != set(contract["required"])
                    or not all(isinstance(v, str) for v in args.values())
                ):
                    raise ValueError(
                        "invalid arguments; use the advertised tool signature"
                    )
                if name == "shell":
                    value = execute(run / "work", args["command"], image)
                elif name == "publish":
                    value = (edition.publish if edition else publish)(run, t, **args)
                elif name == "receipts":
                    value = (
                        edition.online(run, t, args["channel"])
                        if edition
                        else receipts(run, args["channel"])
                    )
                else:
                    raise ValueError("unknown tool")
                result = dict(
                    content=[
                        dict(type="text", text=json.dumps(value, ensure_ascii=False))
                    ]
                )
            except (OSError, KeyError, TypeError, ValueError) as exc:
                result = dict(
                    isError=True,
                    content=[
                        dict(type="text", text=str(exc).replace(str(run), "<desk>"))
                    ],
                )
            with (run / "trace" / f"tools-{t}.jsonl").open("a") as log:
                print(
                    json.dumps(
                        dict(name=name, args=args, result=result), ensure_ascii=False
                    ),
                    file=log,
                )
        else:
            result = {}
        print(
            json.dumps(
                dict(jsonrpc="2.0", id=msg["id"], result=result), ensure_ascii=False
            ),
            flush=True,
        )


def run(dest, edition=None):
    image = subprocess.check_output(
        ["docker", "image", "inspect", "longworkmem-calendar:1", "-f", "{{.Id}}"],
        text=True,
    ).strip()
    dest.mkdir(parents=True, exist_ok=False, mode=0o700)
    (dest / "trace").mkdir()
    (edition.setup if edition else setup)(dest / "work")
    sid = str(uuid.uuid4())
    m = dict(
        model=MODEL,
        harness="Claude Code",
        cli=subprocess.check_output(["claude", "--version"], text=True).strip(),
        image=image,
        session=sid,
        turns=[],
        seed=17217,
        variant="A",
        protocol=edition.VERSION if edition else "calendar-v1",
        status="running",
        reasoning="provider-default",
        limit=None,
        git=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True
        ).strip(),
    )
    if edition:
        m["material_revision"] = edition.MATERIAL_REVISION
        m["scoring_revision"] = edition.SCORING_REVISION
    write(dest / "manifest.json", m)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="calendar-client-") as td,
            Gateway(
                os.environ["ARK_API_KEY"],
                dest,
                allowed=ALLOWED,
                timeout=600,
                private_markers=(
                    "tasks/c2/grade",
                    "C2_PRIVATE_ORACLE",
                    "tasks/c2/cohorts/grade",
                    "tasks/c2/cohorts/reference",
                    "tasks/c2/evolution/grade",
                    "tasks/c2/evolution/reference",
                    "tasks/c2/evolution/oracle",
                ),
            ) as gw,
        ):
            client = Path(td)
            (client / "desk").mkdir()
            for t in range(1, len(edition.PROMPTS) + 1 if edition else 9):
                prompt = (
                    edition.release(dest, t) if edition else release(dest / "work", t)
                )
                if not edition and t == 7:
                    interrupt(dest)
                (dest / "trace" / f"prompt-{t}.txt").write_text(prompt)
                cfg = {
                    "mcpServers": {
                        "calendar": {
                            "command": sys.executable,
                            "args": [
                                "-m",
                                getattr(
                                    edition,
                                    "SERVER_MODULE",
                                    "tasks.c2.evolution.runner",
                                )
                                if edition
                                else "tasks.c2.pilot",
                                "--serve",
                                str(dest),
                                str(t),
                                image,
                            ],
                            "env": {
                                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                                "DOCKER_HOST": os.environ.get(
                                    "DOCKER_HOST", "unix:///var/run/docker.sock"
                                ),
                            },
                        }
                    }
                }
                n = run_claude(
                    dest,
                    t,
                    gw,
                    sid,
                    prompt,
                    client,
                    config=cfg,
                    context=CONTEXT,
                    allowed=ALLOWED,
                    first_session=t == 1,
                )
                freeze(dest / "work", dest / "snapshots" / str(t))
                write(
                    dest / "receipts" / f"{t}.json",
                    {
                        ch: receipts(dest, ch, edition.CHANNELS)
                        for ch in edition.CHANNELS
                    }
                    if edition
                    else {ch: receipts(dest, ch) for ch in ("A", "B")},
                )
                m["turns"].append(dict(turn=t, calls=n))
                write(dest / "manifest.json", m)
                print(t, n, flush=True)
        m["status"] = "complete"
    except BaseException:
        m["status"] = "error"
        raise
    finally:
        write(dest / "manifest.json", m)


if __name__ == "__main__":
    if sys.argv[1] == "--serve":
        serve(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    else:
        run(Path(sys.argv[1]).resolve())
