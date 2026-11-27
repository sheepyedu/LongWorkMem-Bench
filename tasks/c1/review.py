"""Reconcile every upstream exchange with Claude's transcript and the actual workspace journal."""
import argparse
import hashlib
from collections import Counter, defaultdict
import json
import re
from pathlib import Path

from tasks.w1.review import events, show_turn, usage_counts
from .pilot import ALLOWED


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def result_value(value):
    if isinstance(value, list):
        value = "\n".join(p["text"] for p in value if p.get("type") == "text")
    if isinstance(value, str) and value.startswith("<tool_use_error>") and value.endswith("</tool_use_error>"):
        return {"client_error": value}
    return json.loads(value)


def audit(run):
    run = Path(run)
    trace = run / "trace"
    manifest = json.loads((run / "manifest.json").read_text())
    counts = defaultdict(Counter)
    flags, failures, markers, args_changed = [], [], [], []
    assistant_origin_markers = []
    established_filenames = set()
    provider, forwarded, locations = defaultdict(dict), defaultdict(dict), {}
    receipts, sessions = set(), set()
    pending, retries = defaultdict(list), []
    paths = sorted(trace.glob("api-*.json"))
    expected = []
    unforwarded_at_budget = []
    audited_turns = list(manifest["turns"])
    if manifest["status"] == "budget_exhausted":
        partial_turn = len(audited_turns)+1
        previous_attempts = sum(t["upstream_calls"] for t in audited_turns)
        if len(paths) != manifest["limit"]:
            flags.append("Exhausted budget does not match the captured attempt count")
        transcript = trace/f"turn-{partial_turn}.jsonl"
        if transcript.exists():
            partial_session = next((e["session_id"] for _,e in events(transcript)
                                    if isinstance(e,dict) and e.get("session_id")),manifest["session"])
            audited_turns.append(dict(turn=partial_turn,session=partial_session,partial=True,
                                      upstream_calls=len(paths)-previous_attempts))
    for turn in audited_turns:
        expected.extend([turn["turn"]] * turn["upstream_calls"])
    if len(paths) != len(expected):
        flags.append(f"manifest has {len(expected)} attempts, trace has {len(paths)}")
    for number, path in enumerate(paths, 1):
        try:
            row = json.loads(path.read_bytes())
            turn = row["turn"]
            counts[turn]["attempts"] += 1
            if row["n"] != number or path.name != f"api-{number:04}.json" or expected[number-1:number] != [turn]:
                flags.append(f"{path.name}: request number/turn disagrees with manifest")
            wire = row["request"]
            if {t["function"]["name"] for t in wire.get("tools", [])} != ALLOWED:
                flags.append(f"{path.name}: tool list differs")
            if wire["model"] != manifest["model"]:
                flags.append(f"{path.name}: request model differs")
            if turn in manifest.get("rotation_turns", []) and counts[turn]["attempts"] == 1:
                current_prompt = (trace/f"prompt-{turn}.txt").read_text()
                history = wire["messages"]
                if (any(msg["role"] in ("assistant","tool") for msg in history)
                        or current_prompt not in str(history[-1].get("content", ""))):
                    flags.append(f"{path.name}: fresh shift has unexpected prior messages or prompt")
            sent = encoded(wire)
            for marker in ("c1.grade", "c1/grade", "c1/reference", "c1-grade/", "CP4.decision", "CP5.replay",
                           "settlement_grade", "settlement_reference", "archive.preserved", "lineage.close", "dispatch-v1",
                           "reserve_grade", "reserve_reference", "guarantee.rerun",
                           "LongWorkMem-Bench", ".claude-manager/", str(run.resolve())):
                if marker in sent:
                    hits = [msg for msg in wire.get("messages", []) if marker in encoded(msg)]
                    # An assistant can name its own output after a business operation.
                    # Keep host/tool occurrences and mixed or unrecognized text for investigation.
                    only_assistant = hits and all(msg["role"] == "assistant" for msg in hits)
                    filename = re.compile(r"scratch/guarantee\.rerun[0-9]*(?:\.report)?\.json\b")
                    if (marker == "guarantee.rerun" and only_assistant
                            and marker not in encoded({k: v for k, v in wire.items() if k != "messages"})
                            and (marker in established_filenames or all(marker not in filename.sub("", encoded(msg)) for msg in hits))):
                        established_filenames.add(marker)
                        assistant_origin_markers.append([path.name, marker])
                    else:
                        markers.append([path.name, marker])
            for message in wire["messages"]:
                if message["role"] == "tool":
                    value = result_value(message["content"])
                    cid = message["tool_call_id"]
                    if cid in forwarded[turn] and forwarded[turn][cid] != value:
                        flags.append(f"{path.name}: changed tool history {cid}")
                    forwarded[turn][cid] = value
            reply = row.get("response", {})
            fingerprint = turn, hashlib.sha256(sent.encode()).digest()
            status = row.get("status", 0)
            if status in (408, 409, 425, 429) or 500 <= status < 600:
                if not row.get("error"):
                    flags.append(f"{path.name}: missing failure reason")
                retry = {"receipt":path.name,"status":status,"usage_known":bool(reply.get("usage")),"retry":None}
                retries.append(retry)
                pending[fingerprint].append(retry)
                if not reply:
                    counts[turn]["unknown_usage"] += 1
                    continue
            if reply.get("model") != manifest["model"]:
                flags.append(f"{path.name}: absent or different response model")
            usage = usage_counts(reply["usage"])
            if not usage:
                raise ValueError("invalid usage")
            counts[turn].update(usage)
            counts[turn]["peak_input"] = max(counts[turn]["peak_input"], usage["input"])
            if row.get("status") == 200:
                counts[turn]["successful"] += 1
                for retry in pending.pop(fingerprint, []):
                    retry["retry"] = path.name
            elif fingerprint not in pending:
                flags.append(f"{path.name}: delivery status {row.get('status')}")
            ids = {(field, value) for field, value in (("request", row.get("request_id")), ("reply", reply.get("id"))) if value}
            if not ids or ids & receipts:
                flags.append(f"{path.name}: missing or duplicate receipt")
            receipts.update(ids)
            if status != 200:
                continue
            for call in reply["choices"][0]["message"].get("tool_calls", []):
                fn = call["function"]
                provider[turn][call["id"]] = [fn["name"], json.loads(fn["arguments"])]
                locations[(turn, call["id"])] = path.name
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            flags.append(f"{path.name}: {type(exc).__name__}: {str(exc)[:120]}")
    for attempts in pending.values():
        flags.append(f"{attempts[-1]['receipt']}: no matching retry succeeded")
    for turn in audited_turns:
        n = turn["turn"]
        cli, results, terminals = {}, {}, []
        path = trace / f"turn-{n}.jsonl"
        if not path.is_file():
            flags.append(f"{path.name}: missing transcript")
            continue
        for line, event in events(path):
            try:
                if not event:
                    raise ValueError("unreadable event")
                if event.get("session_id"):
                    sessions.add(event["session_id"])
                    if event["session_id"] != turn.get("session",manifest["session"]):
                        flags.append(f"{path.name}:{line}: unexpected shift session")
                if event.get("subtype") == "compact_boundary":
                    counts[n]["compactions"] += 1
                if event["type"] == "result":
                    terminals.append(event.get("is_error"))
                for block in event.get("message", {}).get("content", []):
                    if block["type"] == "tool_use":
                        cli[block["id"]] = [block["name"], block["input"]]
                    elif block["type"] == "tool_result":
                        value = result_value(block["content"])
                        results[block["tool_use_id"]] = value
                        if "client_error" in value:
                            failures.append({"turn": n, "line": line, "client_error": value["client_error"][:200]})
                            if not block.get("is_error"):
                                flags.append(f"{path.name}:{line}: unmarked client rejection")
                        elif value.get("status") != 0:
                            failures.append({"turn": n, "line": line, "status": value.get("status")})
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                flags.append(f"{path.name}:{line}: {type(exc).__name__}")
        if terminals != [bool(turn.get("partial"))]:
            flags.append(f"turn {n}: terminal results {terminals}")
        if cli.keys() != provider[n].keys() or cli.keys() != results.keys():
            flags.append(f"turn {n}: tool call or result IDs differ")
        for cid in cli.keys() & provider[n].keys():
            if cli[cid] != provider[n][cid]:
                item = {"turn": n, "call_id": cid, "receipt": locations[n, cid]}
                args_changed.append(item)
                flags.append(f"turn {n}: provider and executed tool arguments differ at {locations[n, cid]} ({cid})")
        for cid in results:
            if cid in forwarded[n] and forwarded[n][cid] == results[cid]:
                continue
            last_receipt = locations.get((n, cid))
            if (turn.get("partial") and terminals == [True] and manifest.get("budget_exhausted")
                    and len(paths) == manifest["limit"] and paths and last_receipt == paths[-1].name
                    and cid not in forwarded[n]):
                unforwarded_at_budget.append({"turn": n, "call_id": cid, "receipt": last_receipt})
            else:
                flags.append(f"turn {n}: result differs or absent from next upstream input: {cid}")
        observed = Counter(encoded([args, results[cid]]) for cid, (name, args) in cli.items() if cid in results and "client_error" not in results[cid])
        journal = Counter()
        ledger = trace / f"tools-{n}.jsonl"
        if ledger.exists():
            for line, raw in enumerate(ledger.read_bytes().splitlines(), 1):
                try:
                    row = json.loads(raw)
                    journal[encoded([row["args"], row["result"]])] += 1
                except (ValueError, KeyError, TypeError):
                    flags.append(f"{ledger.name}:{line}: unreadable tool journal")
        if journal != observed:
            flags.append(f"turn {n}: host tool journal differs from the CLI")
        counts[n]["tools"] = sum(journal.values())
    expected_sessions = {turn.get("session",manifest["session"]) for turn in audited_turns}
    if sessions != expected_sessions or (manifest.get("status")=="complete" and
            len(expected_sessions) != len(manifest.get("rotation_turns", []))+1):
        flags.append("session identity mismatch")
    totals = Counter()
    for row in counts.values():
        for k, value in row.items():
            if k == "peak_input":
                totals[k] = max(totals[k], value)
            else:
                totals[k] += value
    return {"status": manifest["status"], "turns": dict(sorted(counts.items())), "totals": totals,
            "unforwarded_at_budget": unforwarded_at_budget, "shell_failures": failures, "retry_attempts": retries, "argument_differences": args_changed, "assistant_origin_markers": assistant_origin_markers, "private_markers": markers, "flags": flags}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--turn", choices=range(1, 13), type=int)
    args = p.parse_args()
    if args.turn:
        show_turn(args.run, args.turn)
    else:
        print(json.dumps(audit(args.run), ensure_ascii=False, indent=2))
