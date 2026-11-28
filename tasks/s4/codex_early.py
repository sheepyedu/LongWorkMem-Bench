"""Run and replay S4's early board using one native Codex thread."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

from tasks.codex_client import Client

from .continuation import environment, replay, state_receipt
from .early_league import IMAGE, episode
from .pilot import write
from .tools import TOOLS


def run(dest, ep, image, model, effort):
    dest.mkdir(mode=0o700, parents=True)
    trace = dest / "trace"
    trace.mkdir()
    (trace / "mcp.jsonl").touch()
    meta = dict(
        model=model, effort=effort, harness="codex-app-server", protocol=ep.protocol,
        arm="single", case="site21", opponent="strategic", blocks=[], status="running",
        start=datetime.now(UTC).isoformat(),
        revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        codex=subprocess.check_output(["codex", "--version"], text=True).strip(),
        image=subprocess.check_output(["docker", "image", "inspect", "-f", "{{.Id}}", image], text=True).strip(),
    )
    write(dest / "manifest.json", meta)
    try:
        with (
            environment(meta["image"], trace, dest / "memory.json", "single", "strategic",
                        ep.rules, ep.shared_turns, ep.board) as desk,
            Client(dest, model, effort) as client,
        ):
            session = client.start(ep.context, TOOLS)
            for idx, phase in enumerate(ep.phases, 1):
                desk.start(phase)
                prompt = ep.prompt(phase, "single", "site21")
                (trace / f"prompt-{idx}.txt").write_text(prompt)
                block = dict(index=idx, phase=phase, table=desk.label, session=session,
                             before=state_receipt(desk), first_tool=desk.seq+1)
                meta["blocks"].append(block)
                write(dest / "manifest.json", meta)
                client.turn(idx, prompt, desk.dispatch)
                block.update(after=state_receipt(desk), last_tool=desk.seq)
                write(dest / "manifest.json", meta)
                print(f"{idx} {phase} — position {block['after']['position']}, tools {desk.seq}", flush=True)
                if desk.active.state["finished"]:
                    break
        meta["status"] = "complete"
    except BaseException as exc:
        meta.update(status="failed", error=str(exc))
        raise
    finally:
        meta["end"] = datetime.now(UTC).isoformat()
        write(dest / "manifest.json", meta)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest", type=Path)
    p.add_argument("--model", default="gpt-6.1-terra")
    p.add_argument("--effort", default="low")
    p.add_argument("--length", choices=(32, 40), type=int, default=40)
    p.add_argument("--image")
    p.add_argument("--replay", action="store_true")
    args = p.parse_args()
    ep = episode(args.length)
    if not args.replay:
        run(args.dest, ep, args.image or IMAGE, args.model, args.effort)
    else:
        manifest = json.loads((args.dest/"manifest.json").read_text())
        ep = {episode(n).protocol: episode(n) for n in (32,40)}[manifest["protocol"]]
    score = replay(args.dest, args.image, episode=ep)
    write(args.dest/"grade.json", score)
    print(json.dumps(score, indent=2))


if __name__ == "__main__":
    main()
