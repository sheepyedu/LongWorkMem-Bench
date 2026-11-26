"""Inspect actual model attempts, usage and per-turn Claude Code tool evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path


def events(path):
    with path.open(encoding="utf-8") as lines:
        for n, line in enumerate(lines, 1):
            if line.strip():
                yield n, json.loads(line)


def summarize(run):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text())
    counts, tools = Counter(), Counter()
    per_turn, flagged, missing, models, ids = {}, [], [], set(), set()
    tripwires = ("w1/scoring_", "CP1.join", "CP3.frozen", "CP4.scope", "CP5.recalc",
                 str(run.resolve()), "w1/grade.py", "w1/reference.py")
    for path in sorted((run / "trace").glob("api-*.json")):
        row = json.loads(path.read_text())
        t = per_turn.setdefault(row["turn"], Counter())
        t["attempts"] += 1
        payload = row.get("request", {})
        wire = json.dumps(payload, ensure_ascii=False)
        for marker in tripwires:
            if marker in wire:
                flagged.append((path.name, marker))
        reply = row.get("response", {})
        usage = reply.get("usage")
        if not usage:
            missing.append(path.name)
            continue
        request_id = row.get("request_id") or reply.get("id")
        if request_id and request_id in ids:
            raise ValueError(f"Repeated upstream receipt at {path.name}")
        ids.add(request_id)
        models.add(reply.get("model"))
        for counter in (t, counts):
            counter["successful"] += 1
            counter["input"] += usage["prompt_tokens"]
            counter["output"] += usage["completion_tokens"]
            counter["cache_read"] += usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            counter["reasoning"] += usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
            counter["peak_input"] = max(counter["peak_input"], usage["prompt_tokens"])
    for path in sorted((run / "trace").glob("turn-*.jsonl")):
        turn = int(path.stem.split("-")[1])
        t = per_turn.setdefault(turn, Counter())
        for _, event in events(path):
            if event["type"] == "assistant":
                for b in event["message"]["content"]:
                    if b["type"] == "tool_use":
                        tools[b["name"]] += 1
                        t["tools"] += 1
            elif event["type"] == "system" and event.get("subtype") == "compact_boundary":
                t["compactions"] += 1
            elif event["type"] == "user":
                for b in event.get("message", {}).get("content", []):
                    if b.get("type") == "tool_result" and b.get("is_error"):
                        t["tool_protocol_errors"] += 1
    return {"status": manifest.get("status"), "models": sorted(models), "observed_usage": counts,
            "tools": tools, "attempts_without_usage": missing, "turns": dict(sorted(per_turn.items())),
            "private_markers_in_requests": flagged}


def show_turn(run, turn):
    root = run / "trace"
    prompt = root / f"prompt-{turn}.txt"
    if prompt.exists():
        print(prompt.read_text())
    for n, event in events(root / f"turn-{turn}.jsonl"):
        if event["type"] not in {"assistant", "user", "result"}:
            continue
        for b in event.get("message", {}).get("content", []):
            if b["type"] == "text":
                print(f"[{n} assistant]", b["text"])
            elif b["type"] == "tool_use":
                print(f"[{n} tool {b['id']}]", b["name"], json.dumps(b["input"], ensure_ascii=False))
            elif b["type"] == "tool_result":
                print(f"[{n} result {b['tool_use_id']}]", json.dumps(b["content"], ensure_ascii=False))
        if event["type"] == "result":
            print(f"[{n} terminal]", event["subtype"], event.get("stop_reason"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--turn", choices=range(1,10), type=int)
    args = parser.parse_args()
    if args.turn:
        show_turn(args.run, args.turn)
    else:
        print(json.dumps(summarize(args.run), ensure_ascii=False, indent=2))
