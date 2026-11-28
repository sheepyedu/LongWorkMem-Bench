"""Reconcile the native transcript, upstream attempts, MCP calls and subscriber receipts."""

from collections import Counter
import json
from pathlib import Path
import sys
from .pilot import ALLOWED
from .scenario import PROMPTS


def enc(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def lines(p):
    if not p.exists():
        return []
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]


def result_text(blocks):
    if isinstance(blocks, str):
        return blocks
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def audit(run):
    meta = json.loads((run / "manifest.json").read_text())
    trace = run / "trace"
    ledger = []
    flags = []
    origins = {}
    forwarded = {}
    usage = Counter()
    responded = set()
    per = {}
    first_prompts = {}
    terminal = {}
    answer_sources = {}
    for f in sorted(trace.glob("api-*.json")):
        a = json.loads(f.read_text())
        q = a.get("request", {})
        t = a["turn"]
        if q:
            visible = [
                m.get("content") for m in q.get("messages", []) if m["role"] == "user"
            ]
            first_prompts.setdefault(t, visible)
            if not any(PROMPTS[t - 1] in str(v) for v in visible):
                # Native compaction may remove an older user message; report separately.
                if not first_prompts[t] or PROMPTS[t - 1] not in str(
                    first_prompts[t][-1]
                ):
                    flags.append([f.name, "public prompt absent"])
        wire = enc(q)
        for marker in (
            "C2_PRIVATE_ORACLE",
            "tasks.c2.grade",
            "tasks/c2/grade",
            "tasks/c2/reference",
            "legacy.local-list",
            "recover.unsent",
            "/tmp/lwm-c2-dev",
            str(run.resolve()),
        ):
            if marker in wire:
                flags.append([f.name, "private marker", marker])
        if q and (
            q.get("model") != meta["model"]
            or {x["function"]["name"] for x in q.get("tools", [])} != ALLOWED
        ):
            flags.append([f.name, "model or tools differ"])
        for m in q.get("messages", []):
            if m["role"] == "tool":
                forwarded.setdefault(m["tool_call_id"], set()).add(m["content"])
        r = a.get("response", {})
        receipt = r.get("usage")
        if receipt:
            usage["input"] += receipt["prompt_tokens"]
            usage["output"] += receipt["completion_tokens"]
            usage["peak_input"] = max(usage["peak_input"], receipt["prompt_tokens"])
            cached = (receipt.get("prompt_tokens_details") or {}).get("cached_tokens")
            if cached is None:
                usage["missing_cache"] += 1
            else:
                usage["cached_input"] += cached
        else:
            usage["missing_usage"] += 1
        msg = r.get("choices", [{}])[0].get("message", {})
        if msg.get("content"):
            answer_sources.setdefault(t, []).append(msg["content"].strip())
        if r:
            if r.get("model") != meta["model"] or r.get("id") in responded:
                flags.append([f.name, "response identity"])
            responded.add(r.get("id"))
        for c in msg.get("tool_calls", []):
            try:
                args = json.loads(c["function"]["arguments"])
            except ValueError:
                continue
            origins[c["id"]] = (c["function"]["name"], args)
        ledger.append(
            dict(
                attempt=a["n"],
                turn=t,
                status=a.get("status"),
                failure=a.get("failure_kind"),
                usage=receipt,
            )
        )
    for entry in meta["turns"]:
        t = entry["turn"]
        journal = lines(trace / f"tools-{t}.jsonl")
        cli = lines(trace / f"turn-{t}.jsonl")
        pending = {}
        matched = Counter()
        actions = []
        answers = []
        for event in cli:
            if event.get("session_id", meta["session"]) != meta["session"]:
                flags.append([t, "session changed"])
            if event.get("type") == "result":
                answers.append(event.get("result", ""))
            for b in event.get("message", {}).get("content", []):
                if not isinstance(b, dict):
                    continue
                if b["type"] == "tool_use":
                    cid = b["id"]
                    pending[cid] = (b["name"], b["input"])
                    if origins.get(cid) != pending[cid]:
                        flags.append([t, "upstream call differs", cid])
                if b["type"] == "tool_result":
                    cid = b["tool_use_id"]
                    content = result_text(b.get("content", ""))
                    use = pending.pop(cid, None)
                    if not use:
                        flags.append([t, "unmatched result", cid])
                        continue
                    if content not in forwarded.get(cid, set()):
                        flags.append([t, "tool result not returned upstream", cid])
                    matched[enc([use[0].split("__")[-1], use[1], content])] += 1
        if (
            pending
            or len(answers) != 1
            or sum(a["turn"] == t for a in ledger) != entry["calls"]
        ):
            flags.append([t, "turn reconciliation"])
        if len(answers) == 1 and answers[0].strip() not in answer_sources.get(t, []):
            flags.append([t, "final text differs from provider"])
        if (trace / f"prompt-{t}.txt").read_text() != PROMPTS[t - 1]:
            flags.append([t, "prompt script differs"])
        custody = Counter()
        for j in journal:
            text = result_text(j["result"]["content"])
            custody[enc([j["name"], j["args"], text])] += 1
            try:
                v = json.loads(text)
            except ValueError:
                v = text
            actions.append(
                dict(
                    tool=j["name"],
                    args=j["args"],
                    error=j["result"].get("isError", False),
                    result=v,
                )
            )
        if matched != custody:
            flags.append([t, "MCP result count or content differs"])
        batches = json.loads((run / "receipts" / f"{t}.json").read_text())
        for c in "AB":
            old = terminal.get(c, [])
            if batches[c][: len(old)] != old:
                flags.append([t, c, "receipt history rewritten"])
            observed = Counter(
                (a["args"]["key"], a["result"]["receipt"])
                for a in actions
                if a["tool"] == "publish"
                and a["args"].get("channel") == c
                and isinstance(a["result"], dict)
                and a["result"].get("already_received") is False
            )
            new = batches[c][len(old) :]
            signed = Counter(
                (b["key"], b["receipt"])
                for b in new
                if not (t == 7 and c == "A" and b["key"] == "urgent-0327-A")
            )
            if signed != observed:
                flags.append([t, c, "subscriber records differ from tool receipts"])
            terminal[c] = batches[c]
        per[t] = dict(
            calls=entry["calls"],
            actions=actions,
            answer=answers,
            subscriber={
                c: [
                    dict(key=b["key"], uids=list(b["rows"]))
                    for b in batches[c]
                    if b["turn"] == t
                ]
                for c in "AB"
            },
        )
    return dict(attempts=ledger, usage=usage, flags=flags, turns=per)


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1])), ensure_ascii=False, indent=2))
