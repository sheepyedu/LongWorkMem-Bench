"""Short, evaluator-operated note-retention comparisons from frozen practice positions."""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.w1.claude import run_claude
from tasks.w1.gateway import URL, Gateway

from .engine import connect
from .grade import TARGET_EDGE, evaluate_table
from .pilot import write
from .public import CONTEXT, PRACTICE
from .tools import ALLOWED, Table, broker


def compare(source, dest, upstream, key):
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError("Provide the completed league")
    cutoff = source / "trace/game-3-notes.json"
    notes = json.loads(cutoff.read_text()) if cutoff.exists() else {}
    dest.mkdir(mode=0o700, parents=True)
    report = []
    for name, edge in TARGET_EDGE.items():
        label, assignment = PRACTICE[name]
        conditions = {
            "retained": notes,
            "empty": {},
            "correct_history": {
                "league-assignment": f"Earlier club assignment: practice table {label}, corridor edge {edge}."
            },
        }
        for condition, initial_notes in conditions.items():
            run = dest / name / condition
            run.mkdir(mode=0o700, parents=True)
            (run / "trace").mkdir()
            with (
                connect(manifest["image"]) as engine,
                TemporaryDirectory(prefix="game-client-") as temp,
            ):
                table = Table(engine, run / "trace/mcp.jsonl", run / "memory.json")
                table.notes = dict(initial_notes)
                initial = table.open(name)
                write(
                    run / "initial.json",
                    {"table": label, "notes": table.notes, "state": initial},
                )
                expected = f"Practice table {label}. {assignment} The table is now open. Play the currently pending turn."
                (run / "trace/prompt-1.txt").write_text(expected)
                session = str(uuid.uuid4())
                client = Path(temp)
                (client / "desk").mkdir()
                with (
                    broker(table) as (address, token),
                    Gateway(
                        key,
                        run,
                        allowed=ALLOWED,
                        url=upstream,
                        direct_response=True,
                        timeout=135,
                        private_markers=(str(Path(__file__).resolve().parents[2]),),
                    ) as gateway,
                ):
                    config = {
                        "mcpServers": {
                            "table": {
                                "command": sys.executable,
                                "args": ["-m", "tasks.s4.tools", address, token],
                                "env": {
                                    "PYTHONPATH": str(
                                        Path(__file__).resolve().parents[2]
                                    )
                                },
                            }
                        }
                    }
                    count = run_claude(
                        run,
                        1,
                        gateway,
                        session,
                        expected,
                        client,
                        config=config,
                        context=CONTEXT,
                        allowed=ALLOWED,
                        first_session=True,
                    )
                final = table.request("end_state")
                write(run / "final.json", final)
                checks = evaluate_table(name, final, initial["position"])
                receipt = {
                    "practice": label,
                    "condition": condition,
                    "score": sum(x[0] for x in checks.values()),
                    "checks": checks,
                    "attempts": count,
                    "completed_turn": table.done(),
                }
                write(run / "result.json", receipt)
                report.append(receipt)
                write(dest / "results.json", report)
                print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("dest", type=Path)
    p.add_argument("--upstream", default=URL)
    args = p.parse_args()
    compare(args.source, args.dest, args.upstream, os.environ["ARK_API_KEY"])
