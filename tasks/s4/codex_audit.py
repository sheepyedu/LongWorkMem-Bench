"""Audit S4's recorded Codex tool exchanges against the Docker replay journal."""

import argparse
import json
from pathlib import Path

from tasks.codex_bench import native_usage, recorded_turn

from .early_league import episode
from .grade import read_lines
from .tools import TOOLS


def audit(run):
    trace = run / "trace"
    manifest = json.loads((run / "manifest.json").read_text())
    ep = {episode(n).protocol: episode(n) for n in (32, 40)}[manifest["protocol"]]
    (thread,) = read_lines(trace / "threads.jsonl")
    allowed = [t["name"] for t in TOOLS]
    if (
        manifest["harness"] != "codex-app-server"
        or manifest["status"] != "complete"
        or thread["model"] != manifest["model"]
        or thread["effort"] != manifest["effort"]
        or thread["context"] != ep.context
        or thread["tools"] != allowed
        or thread["environments"] != []
    ):
        raise ValueError("Unexpected Codex model, tools, instructions or environment")
    journal = list(read_lines(trace / "mcp.jsonl"))
    turns = []
    peak = 0
    windows = set()
    errors = []
    compactions = []
    turn_ids = set()
    blocks = manifest["blocks"]
    if {p.name for p in trace.glob("turn-*.jsonl")} != {
        f"turn-{b['index']}.jsonl" for b in blocks
    }:
        raise ValueError("Missing or unaccounted Codex turns")
    for block in blocks:
        i = block["index"]
        if block["session"] != thread["thread"]:
            raise ValueError("Unexpected Codex thread change")
        prompt = ep.prompt(block["phase"], manifest["arm"], manifest["case"])
        answer = recorded_turn(run, i, thread["thread"], prompt, allowed)
        native = []
        updates = 0
        for row in read_lines(trace / f"turn-{i}.jsonl"):
            msg = row["message"]
            method = msg.get("method")
            p = msg.get("params", {})
            if method == "turn/completed":
                tid = p["turn"]["id"]
                if tid in turn_ids:
                    raise ValueError("Repeated turn ID")
                turn_ids.add(tid)
            if method == "thread/tokenUsage/updated":
                if p["threadId"] != thread["thread"]:
                    raise ValueError("Usage attributed to a different session")
                use = p["tokenUsage"]
                peak = max(peak, use["last"]["inputTokens"])
                windows.add(use["modelContextWindow"])
                updates += 1
            if method != "item/completed":
                continue
            item = p["item"]
            if item["type"] == "contextCompaction":
                compactions.append(i)
            if item["type"] == "dynamicToolCall":
                if not item["success"]:
                    raise ValueError(f"Codex tool transport failure at turn {i}")
                value = json.loads(item["contentItems"][0]["text"])
                if "error" in value:
                    errors.append(
                        {"turn": i, "tool": item["tool"], "message": value["error"]}
                    )
                native.append((item["tool"], item["arguments"], value))
        desk = journal[block["first_tool"] - 1 : block["last_tool"]]
        if native != [(r["tool"], r["args"], r["result"]) for r in desk]:
            raise ValueError(f"Native / desk journal mismatch at {i}")
        turns.append(
            {
                "turn": i,
                "phase": block["phase"],
                "tools": len(native),
                "usage_updates": updates,
                "answer": answer,
            }
        )
    usage = native_usage(run, {"turns": [{"attempts": [b["index"]]} for b in blocks]})
    return {
        "model": thread["model"],
        "effort": thread["effort"],
        "sessions": 1,
        "rounds": len(turns),
        "usage": usage,
        "peak_reported_input": peak,
        "reported_context_windows": sorted(windows),
        "compaction_rounds": compactions,
        "tool_errors": errors,
        "turns": turns,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
