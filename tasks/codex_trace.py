"""Verify and count native Codex events without task-specific dependencies."""

import json


def recorded_turn(run, idx, thread, prompt, allowed):
    """Match native turn IDs, the user input, tool round trips and the final answer."""
    path = run / "trace" / f"turn-{idx}.jsonl"
    calls, dispatches = {}, {}
    final = None
    start_id = turn_id = None
    completed = False
    for line in path.read_text().splitlines():
        row = json.loads(line)
        direction, msg = row["direction"], row["message"]
        params = msg.get("params", {})
        method = msg.get("method")
        if method == "turn/start":
            if (
                start_id is not None
                or direction != "send"
                or params["threadId"] != thread
            ):
                raise ValueError("Codex turn start differs")
            if (
                params["input"] != [{"type": "text", "text": prompt}]
                or params["environments"] != []
            ):
                raise ValueError("Codex turn input or environment differs")
            start_id = msg["id"]
        elif (
            method is None
            and direction == "recv"
            and msg.get("id") == start_id
            and "result" in msg
        ):
            turn_id = msg["result"]["turn"]["id"]
        elif method in ("item/completed", "item/tool/call", "turn/completed"):
            event_turn = (
                params["turn"]["id"] if method == "turn/completed" else params["turnId"]
            )
            if (
                not turn_id
                or event_turn != turn_id
                or params["threadId"] != thread
                or completed
            ):
                raise ValueError("Codex event from wrong turn or session")
            if method == "item/tool/call":
                if (
                    params["tool"] not in allowed
                    or msg["id"] in dispatches
                    or params["callId"] in calls
                ):
                    raise ValueError("Unexpected Codex tool")
                dispatches[msg["id"]] = params["callId"]
                calls[params["callId"]] = {
                    "tool": params["tool"],
                    "arguments": params["arguments"],
                }
            elif method == "turn/completed":
                completed = params["turn"]["status"] == "completed"
            else:
                item = params["item"]
                if item["type"] == "agentMessage":
                    final = item["text"]
                elif item["type"] == "dynamicToolCall":
                    call = calls.get(item["id"], {})
                    if any(
                        call.get(k) != item[k]
                        for k in ("tool", "arguments", "success", "contentItems")
                    ):
                        raise ValueError(
                            "Codex tool request or result differs from native completion"
                        )
                    if call.get("done"):
                        raise ValueError("Duplicate tool completion")
                    call["done"] = True
                elif item["type"] not in (
                    "userMessage",
                    "reasoning",
                    "contextCompaction",
                    "plan",
                ):
                    raise ValueError("Unexpected native action " + item["type"])
        elif direction == "send" and "result" in msg:
            if msg["id"] not in dispatches:
                raise ValueError("Unmatched Codex tool response")
            calls[dispatches.pop(msg["id"])].update(msg["result"])
    if (
        not completed
        or final is None
        or dispatches
        or not all(c.get("done") for c in calls.values())
    ):
        raise ValueError("Incomplete native Codex turn")
    return final


def native_usage(run, meta):
    """Totals are cumulative per thread. Keep its last observation across user turns."""
    sessions = {}
    updates = 0
    tools = 0
    compact = 0
    missing = []
    for entry in meta["turns"]:
        for idx in entry["attempts"]:
            observed = False
            for line in (run / "trace" / f"turn-{idx}.jsonl").read_text().splitlines():
                msg = json.loads(line)["message"]
                method = msg.get("method")
                if method == "thread/tokenUsage/updated":
                    params = msg["params"]
                    sessions[params["threadId"]] = params["tokenUsage"]["total"]
                    updates += 1
                    observed = True
                elif method == "item/tool/call":
                    tools += 1
                elif (
                    method == "item/completed"
                    and msg["params"]["item"]["type"] == "contextCompaction"
                ):
                    compact += 1
            if not observed:
                missing.append(idx)
    result = {
        "usage_updates": updates,
        "tool_calls": tools,
        "compact_events": compact,
        "missing_usage_attempts": missing,
    }
    if sessions and not missing:
        for field in (
            "inputTokens",
            "outputTokens",
            "cachedInputTokens",
            "reasoningOutputTokens",
            "totalTokens",
        ):
            result[field] = sum(v[field] for v in sessions.values())
    return result
