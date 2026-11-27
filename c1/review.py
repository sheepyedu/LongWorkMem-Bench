"""Reconcile every upstream exchange with Claude's transcript and the actual workspace journal."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from w1.review import events, show_turn, usage_counts
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
    provider, forwarded, locations = defaultdict(dict), defaultdict(dict), {}
    receipts, sessions = set(), set()
    paths = sorted(trace.glob("api-*.json"))
    expected = []
    for turn in manifest["turns"]:
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
            sent = encoded(wire)
            for marker in ("c1.grade", "c1/grade", "c1/reference", "c1-grade/", "CP4.decision", "CP5.replay",
                           "settlement_grade", "settlement_reference", "archive.preserved", "lineage.close", "dispatch-v1",
                           "reserve_grade", "reserve_reference", "guarantee.rerun",
                           "LongWorkMem-Bench", ".claude-manager/", str(run.resolve())):
                if marker in sent:
                    markers.append([path.name, marker])
            for message in wire["messages"]:
                if message["role"] == "tool":
                    value = result_value(message["content"])
                    cid = message["tool_call_id"]
                    if cid in forwarded[turn] and forwarded[turn][cid] != value:
                        flags.append(f"{path.name}: changed tool history {cid}")
                    forwarded[turn][cid] = value
            reply = row.get("response", {})
            if reply.get("model") != manifest["model"]:
                flags.append(f"{path.name}: absent or different response model")
            usage = usage_counts(reply["usage"])
            if not usage:
                raise ValueError("invalid usage")
            counts[turn].update(usage)
            counts[turn]["peak_input"] = max(counts[turn]["peak_input"], usage["input"])
            if row.get("status") == 200:
                counts[turn]["successful"] += 1
            else:
                flags.append(f"{path.name}: delivery status {row.get('status')}")
            ids = {(field, value) for field, value in (("request", row.get("request_id")), ("reply", reply.get("id"))) if value}
            if not ids or ids & receipts:
                flags.append(f"{path.name}: missing or duplicate receipt")
            receipts.update(ids)
            for call in reply["choices"][0]["message"].get("tool_calls", []):
                fn = call["function"]
                provider[turn][call["id"]] = [fn["name"], json.loads(fn["arguments"])]
                locations[(turn, call["id"])] = path.name
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            flags.append(f"{path.name}: {type(exc).__name__}: {str(exc)[:120]}")
    for turn in manifest["turns"]:
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
        if terminals != [False]:
            flags.append(f"turn {n}: terminal results {terminals}")
        if cli.keys() != provider[n].keys() or cli.keys() != results.keys():
            flags.append(f"turn {n}: tool call or result IDs differ")
        for cid in cli.keys() & provider[n].keys():
            if cli[cid] != provider[n][cid]:
                item = {"turn": n, "call_id": cid, "receipt": locations[n, cid]}
                args_changed.append(item)
                flags.append(f"turn {n}: provider and executed tool arguments differ at {locations[n, cid]} ({cid})")
        for cid in results:
            if forwarded[n].get(cid) != results[cid]:
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
    if sessions != {manifest["session"]}:
        flags.append("session identity mismatch")
    totals = Counter()
    for row in counts.values():
        for k, value in row.items():
            if k == "peak_input":
                totals[k] = max(totals[k], value)
            else:
                totals[k] += value
    return {"status": manifest["status"], "turns": dict(sorted(counts.items())), "totals": totals,
            "shell_failures": failures, "argument_differences": args_changed, "private_markers": markers, "flags": flags}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--turn", choices=range(1, 13), type=int)
    args = p.parse_args()
    if args.turn:
        show_turn(args.run, args.turn)
    else:
        print(json.dumps(audit(args.run), ensure_ascii=False, indent=2))
