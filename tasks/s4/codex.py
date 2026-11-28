"""Run and replay S4's early board using one native Codex thread."""

import subprocess
from datetime import UTC, datetime

from tasks.codex_client import Client

from .records import write
from .runtime import environment, state_receipt
from .schedule import CONTEXT, PHASES, PROMPTS, PROTOCOL
from .tools import TOOLS


def run_codex_game(dest, image, model, effort):
    dest.mkdir(mode=0o700, parents=True)
    trace = dest / "trace"
    trace.mkdir()
    (trace / "mcp.jsonl").touch()
    meta = {
        "model": model,
        "effort": effort,
        "harness": "codex-app-server",
        "protocol": PROTOCOL,
        "arm": "single",
        "case": "site21",
        "opponent": "strategic",
        "blocks": [],
        "status": "running",
        "start": datetime.now(UTC).isoformat(),
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "codex": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "image": subprocess.check_output(
            ["docker", "image", "inspect", "-f", "{{.Id}}", image], text=True
        ).strip(),
    }
    write(dest / "manifest.json", meta)
    try:
        with (
            environment(
                meta["image"],
                trace,
                dest / "memory.json",
            ) as desk,
            Client(dest, model, effort) as client,
        ):
            session = client.start(CONTEXT, TOOLS)
            for idx, phase in enumerate(PHASES, 1):
                desk.start(phase)
                prompt = PROMPTS[phase]
                (trace / f"prompt-{idx}.txt").write_text(prompt)
                block = {
                    "index": idx,
                    "phase": phase,
                    "table": desk.label,
                    "session": session,
                    "before": state_receipt(desk),
                    "first_tool": desk.seq + 1,
                }
                meta["blocks"].append(block)
                write(dest / "manifest.json", meta)
                client.turn(idx, prompt, desk.dispatch)
                block.update(after=state_receipt(desk), last_tool=desk.seq)
                write(dest / "manifest.json", meta)
                print(
                    f"{idx} {phase} — position {block['after']['position']}, tools {desk.seq}",
                    flush=True,
                )
                if desk.active.state["finished"]:
                    break
        meta["status"] = "complete"
    except BaseException as exc:
        meta.update(status="failed", error=str(exc))
        raise
    finally:
        meta["end"] = datetime.now(UTC).isoformat()
        write(dest / "manifest.json", meta)
