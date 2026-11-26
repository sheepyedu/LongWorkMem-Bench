"""Host-side audit of each provider receipt, Claude message and game tool exchange."""
import argparse
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path

from w1.review import show_turn, usage_counts
from .table import ALLOWED


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@contextmanager
def check_record(location, remarks):
    try:
        yield
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError) as exc:
        remarks.append(f"{location}: invalid record ({type(exc).__name__})")


def rows(path, remarks):
    with path.open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError
            except (ValueError, UnicodeError):
                remarks.append(f"{path.name}:{line}: unreadable row")
                continue
            yield line, value


def tool_result(block):
    """Decode the game payload as returned by Claude's stdio MCP client."""
    value = block["content"]
    if isinstance(value, list) and len(value) == 1:
        value = value[0]["text"]
    return json.loads(value)


def audit(run):
    run = Path(run)
    trace = run / "trace"
    remarks = []
    manifest = {}
    with check_record("manifest.json", remarks):
        value = json.loads((run / "manifest.json").read_bytes())
        if not isinstance(value, dict) or not isinstance(value.get("turns", []), list):
            raise ValueError("invalid manifest")
        manifest = value
    per_turn = {}
    totals = Counter()
    expected_calls = {}
    actual_tools = set()
    models, receipts, sessions = set(), set(), set()
    markers = ("s1/grade.py", "s1.grade", "s1-grade/", "snapshots/7.json", "table.sqlite",
               str(run.resolve()), ".claude-manager/worktrees/", ".claude-manager/runs/")
    for path in sorted(trace.glob("api-*.json")):
        with check_record(path.name, remarks):
            record = json.loads(path.read_bytes())
            turn = record["turn"]
            if type(turn) is not int:
                raise ValueError("invalid turn")
            counts = per_turn.setdefault(turn, Counter())
            counts["attempts"] += 1
            wire = record.get("request", {})
            serialized = key(wire)
            for marker in markers:
                if marker in serialized:
                    remarks.append(f"{path.name}: private marker {marker}")
            tools = {tool["function"]["name"] for tool in wire.get("tools", [])}
            actual_tools.update(tools)
            if tools - ALLOWED:
                remarks.append(f"{path.name}: unexpected tools {sorted(tools - ALLOWED)}")
            reply = record.get("response", {})
            usage = reply.get("usage", {})
            if not usage:
                remarks.append(f"{path.name}: status={record.get('status')}, receipt={bool(usage)}")
                continue
            usage_values = usage_counts(usage)
            if usage_values is None or not isinstance(reply.get("model"), str):
                raise ValueError("incomplete response")
            models.add(reply["model"])
            receipt = record.get("request_id") or reply.get("id")
            if not receipt or receipt in receipts:
                remarks.append(f"{path.name}: missing or repeated receipt ID")
            receipts.add(receipt)
            counts["receipts"] += 1
            counts["input"] += usage_values["input"]
            counts["output"] += usage_values["output"]
            counts["cached"] += usage_values.get("cache_read", 0)
            counts["peak_input"] = max(counts["peak_input"], usage["prompt_tokens"])
            if record.get("status") != 200:
                counts["bridge_failures"] += 1
                remarks.append(f"{path.name}: bridge status {record.get('status')}, provider usage retained")
                continue
            for call in reply["choices"][0]["message"].get("tool_calls") or []:
                call_id = (turn, call["id"])
                if call_id in expected_calls:
                    remarks.append(f"{path.name}: duplicate tool call ID")
                expected_calls[call_id] = (call["function"]["name"], json.loads(call["function"]["arguments"]))

    for path in sorted(trace.glob("turn-*.jsonl")):
        if not path.stem.removeprefix("turn-").isdigit():
            remarks.append(f"{path.name}: invalid turn number")
            continue
        turn = int(path.stem.removeprefix("turn-"))
        counts = per_turn.setdefault(turn, Counter())
        calls, results = {}, {}
        terminals = []
        for line, entry in rows(path, remarks):
            with check_record(f"{path.name}:{line}", remarks):
                if entry.get("session_id"):
                    sessions.add(entry["session_id"])
                if entry.get("subtype") == "compact_boundary":
                    counts["compactions"] += 1
                if entry["type"] == "result":
                    terminals.append(entry.get("is_error"))
                for block in entry.get("message", {}).get("content", []):
                    if block["type"] == "tool_use":
                        calls[block["id"]] = (block["name"], block["input"])
                    elif block["type"] == "tool_result":
                        try:
                            results[block["tool_use_id"]] = tool_result(block)
                        except (TypeError, ValueError, KeyError):
                            remarks.append(f"{path.name}:{line}: result outside the game protocol")
        if terminals != [False]:
            remarks.append(f"{path.name}: terminal results {terminals}")
        upstream = {cid: action for (t, cid), action in expected_calls.items() if t == turn}
        if upstream != calls or set(calls) != set(results):
            remarks.append(f"{path.name}: provider/Claude call IDs or results differ")
        cli = Counter(key([name.removeprefix("mcp__table__"), args, results[cid]])
                      for cid, (name, args) in calls.items() if cid in results)
        ledger = Counter()
        journal = trace / f"tools-{turn}.jsonl"
        if journal.exists():
            for line, row in rows(journal, remarks):
                with check_record(f"{journal.name}:{line}", remarks):
                    ledger[key([row["tool"], row["args"], row["result"]])] += 1
                    counts["tool_calls"] += 1
                    if row["result"].get("ok") is False:
                        counts["rejections"] += 1
        else:
            remarks.append(f"{journal.name}: missing host journal")
        if cli != ledger:
            remarks.append(f"{path.name}: actual tool exchanges differ from host journal")
    for scheduled in manifest.get("turns", []):
        with check_record("manifest.json", remarks):
            number = scheduled["turn"]
            if per_turn.get(number, {}).get("attempts", 0) != scheduled["upstream_calls"]:
                remarks.append(f"turn {number}: provider attempt count differs from manifest")
            if not (trace / f"turn-{number}.jsonl").is_file():
                remarks.append(f"turn {number}: missing Claude stream")
    if len(sessions) != 1 or manifest.get("session") not in sessions:
        remarks.append("Claude session identity mismatch")
    for counts in per_turn.values():
        for field, value in counts.items():
            if field == "peak_input":
                totals[field] = max(totals[field], value)
            else:
                totals[field] += value
    return {"status": manifest.get("status"), "models": sorted(models), "tools": sorted(actual_tools),
            "turns": dict(sorted(per_turn.items())), "totals": totals, "audit_flags": remarks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--turn", type=int, choices=range(1, 9), help="show every Claude message and tool exchange")
    args = parser.parse_args()
    if args.turn:
        show_turn(args.run, args.turn)
    else:
        print(json.dumps(audit(args.run), ensure_ascii=False, indent=2))
