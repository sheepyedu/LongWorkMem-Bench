"""Inspect actual model attempts, usage and per-turn Claude Code tool evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path


def events(path):
    with path.open("rb") as lines:
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                event = None
            yield n, event if isinstance(event, dict) and isinstance(event.get("type"), str) else None


def shell_status(content):
    # Claude can store an MCP text result as a string or as a list of text blocks.
    texts = [content] if isinstance(content, str) else (
        block.get("text", "") for block in content if block.get("type") == "text"
    )
    for text in texts:
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and type(value.get("status")) is int:
            return value["status"]
    return None


def usage_counts(usage):
    totals = {"input": usage.get("prompt_tokens"), "output": usage.get("completion_tokens")}
    for name, group, field in (
        ("cache_read", "prompt_tokens_details", "cached_tokens"),
        ("reasoning", "completion_tokens_details", "reasoning_tokens"),
    ):
        details = usage.get(group)
        if isinstance(details, dict) and field in details:
            totals[name] = details[field]
    if any(type(value) is not int or value < 0 for value in totals.values()):
        return None
    return totals


def summarize(run):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text())
    counts, tools = Counter(), Counter()
    per_turn, flagged, missing, models, ids = {}, [], [], set(), set()
    expected_turns = {}
    sequence = 1
    for turn in manifest.get("turns", []):
        calls = turn["upstream_calls"]
        per_turn[turn["turn"]] = Counter(expected_attempts=calls)
        for number in range(sequence, sequence + calls):
            expected_turns[f"api-{number:04}.json"] = turn["turn"]
        sequence += calls
    paths = sorted((run / "trace").glob("api-*.json"))
    missing_files = sorted(expected_turns.keys() - {path.name for path in paths})
    record_issues, shell_failures = [], []
    tripwires = ("w1/scoring_", "CP1.join", "CP3.frozen", "CP4.scope", "CP5.recalc",
                 str(run.resolve()), "w1/grade.py", "w1/reference.py", "LongWorkMem-Bench",
                 ".claude-manager/", "w1-grade/", "w1/advanced", "w1-advanced/",
                 "pay.workbook_edited_hours", "ledger.current.warehouse", "w1/paired.py")
    exposed_reports = []
    for path in paths:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, dict) or type(row.get("turn")) is not int:
                raise ValueError
        except (OSError, ValueError):
            record_issues.append({"file": path.name, "reason": "unreadable request record"})
            continue
        expected = expected_turns.get(path.name)
        if type(row.get("n")) is not int or path.name != f"api-{row['n']:04}.json":
            record_issues.append({"file": path.name, "reason": "request sequence differs from filename"})
        if expected is None and manifest.get("status") == "complete":
            record_issues.append({"file": path.name, "reason": "request outside completed manifest"})
        elif expected is not None and row["turn"] != expected:
            record_issues.append({"file": path.name, "reason": f"expected turn {expected}, recorded turn {row['turn']}"})
        t = per_turn.setdefault(row["turn"], Counter())
        t["attempts"] += 1
        payload = row.get("request", {})
        wire = json.dumps(payload, ensure_ascii=False)
        for marker in tripwires:
            if marker in wire:
                flagged.append((path.name, marker))
        for msg in payload.get("messages", []):
            body = msg.get("content")
            if (msg.get("role") in {"tool", "system", "user"} and isinstance(body, str) and
                    '"scorer_version"' in body and "w1-advanced/" in body and
                    '"items"' in body and '"earned"' in body):
                exposed_reports.append(path.name)
                break
        reply = row.get("response")
        usage = reply.get("usage") if isinstance(reply, dict) else None
        if usage is None:
            missing.append(path.name)
            continue
        totals = usage_counts(usage) if isinstance(usage, dict) else None
        if totals is None:
            missing.append(path.name)
            record_issues.append({"file": path.name, "reason": "incomplete or invalid usage"})
            continue
        receipt_ids = {(name, value) for name, value in (("request", row.get("request_id")), ("reply", reply.get("id")))
                       if isinstance(value, str) and value}
        if receipt_ids & ids:
            record_issues.append({"file": path.name, "reason": "duplicate upstream receipt"})
            continue
        ids.update(receipt_ids)
        if isinstance(reply.get("model"), str):
            models.add(reply["model"])
        for counter in (t, counts):
            counter["successful"] += 1
            counter.update(totals)
            counter["peak_input"] = max(counter["peak_input"], totals["input"])
    turn_issues = []
    for path in sorted((run / "trace").glob("turn-*.jsonl")):
        turn = int(path.stem.split("-")[1])
        t = per_turn.setdefault(turn, Counter())
        shell_ids = set()
        for line, event in events(path):
            if event is None:
                turn_issues.append({"file": path.name, "line": line, "reason": "unreadable Claude event"})
                continue
            if event["type"] == "assistant":
                for b in event["message"]["content"]:
                    if b["type"] == "tool_use":
                        tools[b["name"]] += 1
                        t["tools"] += 1
                        if b["name"] == "mcp__office__shell":
                            shell_ids.add(b["id"])
            elif event["type"] == "system" and event.get("subtype") == "compact_boundary":
                t["compactions"] += 1
            elif event["type"] == "user":
                for b in event.get("message", {}).get("content", []):
                    if b.get("type") != "tool_result":
                        continue
                    if b.get("is_error"):
                        t["tool_protocol_errors"] += 1
                    elif b["tool_use_id"] in shell_ids:
                        status = shell_status(b.get("content", []))
                        if status is not None and status != 0:
                            t["shell_nonzero_exits"] += 1
                            shell_failures.append({"file": path.name, "line": line, "status": status})
    return {"status": manifest.get("status"), "models": sorted(models), "observed_usage": counts,
            "tools": tools, "attempts_without_usage": missing, "turns": dict(sorted(per_turn.items())),
            "missing_request_files": missing_files, "request_record_issues": record_issues,
            "turn_record_issues": turn_issues, "shell_failures": shell_failures, "private_markers_in_requests": flagged,
            "exposed_score_reports": exposed_reports}


def show_turn(run, turn):
    root = run / "trace"
    prompt = root / f"prompt-{turn}.txt"
    if prompt.exists():
        print(prompt.read_text())
    for n, event in events(root / f"turn-{turn}.jsonl"):
        if event is None:
            print(f"[{n} unreadable Claude event]")
            continue
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
