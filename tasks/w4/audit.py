"""Read every native event, upstream attempt and journal entry; reconcile business evidence."""

import argparse
from collections import Counter, defaultdict
import json
import unicodedata
from pathlib import Path

from tasks.transcript import enc, lines, result_text
from .grade import grade
from .office import ALLOWED, TOOLS, events
from .pilot import CONTEXT
from .scenario import PROMPTS, ROUNDS


def audit(run):
    run = Path(run)
    trace = run / "trace"
    meta = json.loads((run / "manifest.json").read_text())
    if meta["status"] != "complete" or [x["turn"] for x in meta["turns"]] != list(
        ROUNDS
    ):
        raise ValueError("Only a completed twelve-turn play has a formal audit")
    score = grade(run)
    from .annex import NOTICES

    public = [
        f"6月{i}日。"
        + PROMPTS[i - 1]
        + (NOTICES.get(i, "") if meta["protocol"] == "w4-release-v2" else "")
        for i in ROUNDS
    ]
    attempts = []
    records = defaultdict(list)
    allowed_responses = defaultdict(set)
    origins = {}
    usage = Counter()
    flags = []
    response_ids = set()
    for path in sorted(trace.glob("api-*.json")):
        packet = json.loads(path.read_text())
        t = packet["turn"]
        n = packet["n"]
        q = packet.get("request", {})
        resp = packet.get("response", {})
        if n != len(attempts) + 1 or path.name != f"api-{n:04}.json":
            flags.append([n, "attempt sequence"])
        wire = enc(q)
        if q:
            known_prompts = set(public[:t])
            visible = [m["content"] for m in q["messages"] if m["role"] == "user"]
            if (
                not visible
                or set(visible) - known_prompts
                or visible[-1] != public[t - 1]
            ):
                flags.append(
                    [n, "unexpected user context (inspect compaction if present)"]
                )
            definitions = {
                f["function"]["name"]: (
                    f["function"]["description"],
                    f["function"]["parameters"],
                )
                for f in q.get("tools", [])
            }
            public_definitions = {
                "mcp__office__" + s["name"]: (s["description"], s["inputSchema"])
                for s in TOOLS
            }
            # Claude Code normalizes full-width punctuation in tool descriptions.
            if unicodedata.normalize("NFKC", enc(definitions)) != unicodedata.normalize(
                "NFKC", enc(public_definitions)
            ):
                flags.append([n, "business tool definition differs"])
            if (
                q["model"] != meta["model"]
                or {x["function"]["name"] for x in q.get("tools", [])} != ALLOWED
            ):
                flags.append([n, "unexpected model or tool schema"])
            for marker in (
                "W4_PRIVATE_ORACLE_7cf2",
                "tasks.w4.grade",
                "tasks/w4/grade",
                "w4-implementation",
                "/snapshots/",
                "work-bench/SKILL",
                "w4-release-v1/grade.json",
                str(run.resolve()),
            ):
                if marker in wire:
                    flags.append([n, "private marker", marker])
            systems = [m["content"] for m in q["messages"] if m["role"] == "system"]
            if systems not in (
                [CONTEXT],
                [
                    "You are a Claude agent, built on Anthropic's Claude Agent SDK.\n"
                    + CONTEXT
                ],
            ):
                flags.append([n, "system instructions differ"])
            for m in q["messages"]:
                if m["role"] == "tool":
                    allowed_responses[m["tool_call_id"]].add(m["content"])
        tokens = resp.get("usage", {})
        if resp:
            if (
                resp["model"] != meta["model"]
                or not resp.get("id")
                or resp["id"] in response_ids
            ):
                flags.append([n, "provider identity"])
            response_ids.add(resp["id"])
            msg = resp["choices"][0]["message"]
            for call in msg.get("tool_calls", []):
                try:
                    args = json.loads(call["function"]["arguments"])
                except ValueError:
                    continue
                origins[call["id"]] = (call["function"]["name"], args)
            if msg.get("content"):
                records[t].append(msg["content"].strip())
        if tokens:
            usage["input"] += tokens["prompt_tokens"]
            usage["output"] += tokens["completion_tokens"]
            usage["peak_input"] = max(usage["peak_input"], tokens["prompt_tokens"])
            cached = tokens.get("prompt_tokens_details", {}).get("cached_tokens")
            if cached is None:
                usage["missing_cache"] += 1
            else:
                usage["cached_input"] += cached
        else:
            usage["missing_usage"] += 1
        attempts.append(
            dict(
                n=n,
                t=t,
                status=packet.get("status"),
                failure=packet.get("failure_kind"),
                usage=tokens or None,
            )
        )
    per = []
    for entry in meta["turns"]:
        t = entry["turn"]
        journal = lines(trace / f"tools-{t}.jsonl")
        native = lines(trace / f"turn-{t}.jsonl")
        prompt = (trace / f"prompt-{t}.txt").read_text()
        if prompt != public[t - 1]:
            flags.append([t, "prompt mismatch"])
        matches = Counter()
        actual = Counter()
        finals = []
        waiting = {}
        rejected = []
        compacts = 0
        actions = []
        for e in native:
            if e.get("session_id", meta["session"]) != meta["session"]:
                flags.append([t, "session mismatch"])
            if e.get("subtype") == "compact_boundary":
                compacts += 1
            if e.get("type") == "result":
                finals.append(e.get("result", "").strip())
            for b in e.get("message", {}).get("content", []):
                if not isinstance(b, dict):
                    continue
                if b["type"] == "tool_use":
                    ident = b["id"]
                    waiting[ident] = (b["name"], b["input"])
                    if waiting[ident] != origins.get(ident):
                        flags.append([t, "origin mismatch"])
                if b["type"] == "tool_result":
                    ident = b["tool_use_id"]
                    call = waiting.pop(ident, None)
                    txt = result_text(b.get("content", ""))
                    if not call or txt not in allowed_responses.get(ident, set()):
                        flags.append([t, "tool output provenance"])
                    if call and call[0] not in ALLOWED:
                        rejected.append(dict(name=call[0], error=txt[:240]))
                    elif call:
                        matches[enc((call[0].split("__")[-1], call[1], txt))] += 1
        observed_mail = {}
        for j in journal:
            txt = result_text(j["result"]["content"])
            actual[enc((j["name"], j["args"], txt))] += 1
            try:
                v = json.loads(txt)
            except (ValueError, TypeError):
                v = txt
            err = bool(j["result"].get("isError")) or (
                j["name"] == "shell" and isinstance(v, dict) and v.get("status") != 0
            )
            actions.append(dict(tool=j["name"], args=j["args"], result=v, error=err))
            if j["name"] in ("draft", "deliver") and not err:
                observed_mail[v["receipt"]] = dict(action=j["name"], **j["args"])
        store = {
            e["receipt"]: {
                k: e[k] for k in ("action", "recipient", "subject", "attachment")
            }
            for e in events(run, t, None)
            if e["turn"] == t
        }
        if observed_mail != store:
            flags.append([t, "business mail journal mismatch"])
        if matches != actual or waiting:
            flags.append([t, "tool journal mismatch"])
        if len(finals) != 1 or finals[0] not in records[t]:
            flags.append([t, "final response mismatch"])
        if entry["calls"] != sum(a["t"] == t for a in attempts):
            flags.append([t, "missing upstream attempt"])
        usage["native_compactions"] += compacts
        per.append(
            dict(
                turn=t,
                requests=entry["calls"],
                earned=score["rounds"][t - 1],
                actions=actions,
                compactions=compacts,
                rejected=rejected,
                final=finals,
                mail=store,
            )
        )
    return dict(attempts=attempts, usage=dict(usage), rounds=per, flags=flags)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.run), ensure_ascii=False, indent=2))
