"""Cross-check every provider request, native Claude event and executed player tool."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from .grade import read_lines
from .tools import ALLOWED

PRIVATE_MARKERS = (
    "assigned_edge",
    "road_after_purchase",
    "first_attempt",
    "purchase_cost",
    "score_state",
    "TRADE_CAP",
    "TARGET_EDGE",
    "/tasks/s4/grade.py",
    "checks.csv",
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content(value):
    if isinstance(value, str):
        return value
    return "\n".join(
        x.get("text", "") for x in (value or []) if x.get("type") == "text"
    )


def attempt_calls(message):
    for call in message.get("tool_calls", []) or []:
        try:
            yield (
                call["id"],
                call["function"]["name"],
                json.loads(call["function"]["arguments"]),
            )
        except (ValueError, KeyError, TypeError):
            continue


def inspect(run):
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError("Wait for a terminal benchmark run")
    trace = run / "trace"
    journal = list(read_lines(trace / "mcp.jsonl"))
    request_files = sorted(
        trace.glob("api-*.json"), key=lambda p: int(p.stem.split("-")[1])
    )
    request_rows, tool_rows, segments, model_messages = [], [], [], []
    faults = []
    usage_totals = Counter()
    upstream_ids = set()
    latest_request = 0
    compact = 0
    for block in manifest["blocks"]:
        idx = block["index"]
        name = block["table"]
        events = list(read_lines(trace / f"turn-{idx}.jsonl"))
        initial = [
            e
            for e in events
            if e.get("type") == "system" and e.get("subtype") == "init"
        ]
        if (
            len(initial) != 1
            or set(initial[0]["tools"]) != ALLOWED
            or initial[0]["session_id"] != block["session"]
            or initial[0]["model"] != manifest["model"]
            or [(s["name"], s["status"]) for s in initial[0]["mcp_servers"]]
            != [("table", "connected")]
        ):
            faults.append(f"Segment {idx}: native model, session or allowlist differs")
        compact += sum(e.get("subtype") == "compact_boundary" for e in events)
        original_prompt = (trace / f"prompt-{idx}.txt").read_text()
        calls = {}
        tool_returns = {}
        native_result = []
        for e in events:
            if e.get("type") == "result":
                native_result.append(e.get("result", ""))
            if e.get("type") not in ("assistant", "user"):
                continue
            for item in e.get("message", {}).get("content", []):
                if item["type"] == "text" and e["type"] == "assistant":
                    model_messages.append(
                        {
                            "segment": idx,
                            "table": name,
                            "native_event": e.get("uuid"),
                            "text": item["text"],
                        }
                    )
                if item["type"] == "tool_use":
                    value = (item["name"], canonical(item["input"]))
                    if item["id"] in calls and calls[item["id"]] != value:
                        faults.append(f"Segment {idx}: conflicting native tool ID")
                    calls[item["id"]] = value
                if item["type"] == "tool_result":
                    tool_returns[item["tool_use_id"]] = (
                        content(item["content"]),
                        bool(item.get("is_error")),
                    )
        if len(native_result) != 1:
            faults.append(f"Segment {idx}: expected one final result")
        request_proposals = {}
        accepted = {}
        attempts = request_files[block["first_request"] - 1 : block["last_request"]]
        for path in attempts:
            row = json.loads(path.read_text())
            n = int(path.stem.split("-")[1])
            if row.get("n") != n or row.get("turn") != idx or n != latest_request + 1:
                faults.append(f"Request {n}: numbering differs")
            latest_request = n
            req, reply = row.get("request", {}), row.get("response", {})
            req_msgs = req.get("messages", [])
            names = {t["function"]["name"] for t in req.get("tools", [])}
            if req and (
                req["model"] != manifest["model"]
                or names != ALLOWED
                or req.get("thinking") != {"type": "disabled"}
            ):
                faults.append(f"Request {n}: provider configuration differs")
            indicators = []
            for m in req_msgs:
                if m["role"] in ("user", "tool", "system"):
                    value = content(m.get("content"))
                    indicators.extend(k for k in PRIVATE_MARKERS if k in value)
                    if m["role"] == "tool" and m.get("tool_call_id") in tool_returns:
                        expected = tool_returns[m["tool_call_id"]][0]
                        if value == expected:
                            accepted[m["tool_call_id"]] = True
            if req and n == block["first_request"]:
                if block["first_session"] and [m["role"] for m in req_msgs] != [
                    "system",
                    "user",
                ]:
                    faults.append(f"Segment {idx}: fresh match has prior transcript")
                users = [m["content"] for m in req_msgs if m["role"] == "user"]
                if not any(original_prompt.strip() in u for u in users):
                    faults.append(
                        f"Segment {idx}: first request missing exact task message"
                    )
            if indicators:
                faults.append(f"Request {n}: private marker in inbound text")
            use = reply.get("usage", {})
            if reply:
                if (
                    reply.get("model") != manifest["model"]
                    or not reply.get("id")
                    or reply["id"] in upstream_ids
                ):
                    faults.append(f"Request {n}: unexpected upstream identity")
                upstream_ids.add(reply.get("id"))
                for ident, t, args in attempt_calls(
                    reply.get("choices", [{}])[0].get("message", {})
                ):
                    request_proposals[ident] = (t, canonical(args))
            if use:
                usage_totals["input"] += use["prompt_tokens"]
                usage_totals["output"] += use["completion_tokens"]
                cached = (use.get("prompt_tokens_details") or {}).get("cached_tokens")
                usage_totals["peak_input"] = max(
                    usage_totals["peak_input"], use["prompt_tokens"]
                )
                if cached is not None:
                    usage_totals["cached"] += cached
                    usage_totals["cache_records"] += 1
                reasoning = (use.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens"
                )
                if reasoning is not None:
                    usage_totals["reasoning"] += reasoning
                    usage_totals["reasoning_records"] += 1
                usage_totals["usage_records"] += 1
            request_rows.append(
                {
                    "request": n,
                    "segment": idx,
                    "table": name,
                    "status": row.get("status"),
                    "model": reply.get("model"),
                    "input": use.get("prompt_tokens"),
                    "output": use.get("completion_tokens"),
                    "history_messages": len(req_msgs),
                    "failure_kind": row.get("failure_kind"),
                    "private_markers": ",".join(indicators),
                }
            )
        native_journal = []
        for ident, (t, args) in calls.items():
            if request_proposals.get(ident) != (t, args):
                faults.append(
                    f"Segment {idx}: native action {ident} has no exact provider proposal"
                )
            returned, is_error = tool_returns.get(ident, ("", True))
            try:
                material = json.loads(returned)
            except (ValueError, TypeError):
                material = None
            if t in ALLOWED and isinstance(material, dict) and not is_error:
                native_journal.append(
                    (t.removeprefix("mcp__table__"), args, canonical(material), ident)
                )
            elif not returned:
                faults.append(f"Segment {idx}: missing native result {ident}")
        actions = journal[block["first_tool"] - 1 : block["last_tool"]]
        remaining = Counter((t, args, result) for t, args, result, _ in native_journal)
        forwarded = Counter(
            (t, args, r) for t, args, r, ident in native_journal if accepted.get(ident)
        )
        for action in actions:
            key = (
                action["tool"],
                canonical(action["args"]),
                canonical(action["result"]),
            )
            if remaining[key] <= 0:
                faults.append(
                    f"Journal {action['seq']}: no matching native action and result"
                )
            remaining[key] -= 1
            received = forwarded[key] > 0
            if received:
                forwarded[key] -= 1
            res = action["result"]
            tool_rows.append(
                {
                    "seq": action["seq"],
                    "segment": idx,
                    "table": name,
                    "tool": action["tool"],
                    "args": canonical(action["args"]),
                    "action": res.get("event", {}).get("action"),
                    "event_seq": res.get("event", {}).get("seq"),
                    "error": res.get("error"),
                    "seen_in_provider_history": received,
                }
            )
        if any(remaining.values()):
            faults.append(f"Segment {idx}: journal/native action multiset differs")
        segments.append(
            {
                "segment": idx,
                "table": name,
                "start": block["start_position"],
                "end": block["end_position"],
                "requests": len(attempts),
                "tools": len(actions),
                "response": native_result[-1] if native_result else "",
            }
        )
    if latest_request != len(request_files):
        faults.append("Unaccounted provider attempt")
    counts = Counter(r["tool"] for r in tool_rows)
    return {
        "summary": {
            "requests": len(request_rows),
            "usage": dict(usage_totals),
            "tools": dict(counts),
            "rejected": sum(bool(x["error"]) for x in tool_rows),
            "failed_attempts": sum(r["status"] != 200 for r in request_rows),
            "model_visible_tool_records": sum(
                x["seen_in_provider_history"] for x in tool_rows
            ),
            "compact_events": compact,
            "segments": len(segments),
            "faults": faults,
        },
        "requests": request_rows,
        "tools": tool_rows,
        "segments": segments,
        "messages": model_messages,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    args = p.parse_args()
    report = inspect(args.run)
    for kind in ("requests", "tools", "segments"):
        rows = report[kind]
        if rows:
            with (args.run / f"audit-{kind}.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    (args.run / "audit-messages.json").write_text(
        json.dumps(report["messages"], ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if report["summary"]["faults"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
