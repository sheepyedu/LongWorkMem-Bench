"""Reconcile sealed bookings and provider usage, then pair the two models by season."""
import argparse
from collections import Counter, defaultdict
from itertools import product
import json
from pathlib import Path
from statistics import mean

from .relay import Season
from .relay_pilot import evaluate, final_result


def dependency_groups(season, row):
    """Mark fields on which ignoring a specific history operation changes the answer."""
    team, phase = row["team"], row["phase"]
    cutoff = {"预选": 4, "邀请": 5, "决赛": 7}[phase]
    def infer(field, *, honor_withdrawals=True, expire=True, until=cutoff):
        value = season.base[team][field]
        for d in season.notices:
            allowed = d.scope in ("全季", phase) or (not expire and d.scope == "邀请")
            if (allowed and d.team == team and d.field == field and d.official
                    and d.turn <= until and (not honor_withdrawals or season.withdrawn.get(d.number, 99) > until)):
                value = d.value
        return value
    for i, expected in enumerate(row["expected"]):
        if infer(i, honor_withdrawals=False) != expected:
            yield "撤回后回退", i
        if phase == "决赛" and infer(i, expire=False) != expected:
            yield "邀请专项到期", i
        if row["turn"] == 8 and infer(i, until=7) != expected:
            yield "历史截止", i


def inspect(run):
    meta = json.loads((run / "manifest.json").read_text())
    result = evaluate(run)
    season = Season(meta["seed"], meta["level"], meta["variant"], meta.get("edition", "original"))
    counts, labels = Counter(), defaultdict(lambda: [0, 0])
    flags = []
    attempts = sorted((run / "trace").glob("api-*.json"))
    previous_session = None
    prior_note = ""
    original_prompts = {}
    cold = meta["condition"] in ("current", "evidence")
    first_calls = set()
    scheduled = set()
    for trip in meta["turns"]:
        scheduled.update(trip["calls"])
        turn = trip["turn"]
        expected_reset = cold or turn == 1 or (meta["condition"] == "relay" and turn in (4, 7, 8))
        if (trip["session"] != previous_session) != expected_reset:
            flags.append(f"R{turn}: unexpected session boundary")
        originals = [t for t in season.bulletins if t < turn] if meta["condition"] == "evidence" else []
        original_prompts[turn] = season.prompt(turn, prior_note, meta["condition"], originals)
        if (run / "trace" / f"prompt-{turn}.txt").read_text() != original_prompts[turn]:
            flags.append(f"R{turn}: public briefing differs")
        if trip["session"] != previous_session:
            first_calls.add(trip["calls"][0])
        previous_session = trip["session"]
        rec = json.loads((run / f"receipt-{trip['turn']}.json").read_text())
        prior_note = "" if cold else rec["note"]
        counts["clipped"] += rec["note_length"] > season.capacity
        counts["rejected_rows"] += len(rec["rejected"])
        counts["format_retries"] += len(trip["calls"])-1
    provider_text = defaultdict(list)
    seen = set()
    ids = set()
    for f in attempts:
        d = json.loads(f.read_text())
        payload = d.get("request", {})
        reply = d.get("response", {})
        turn = d["turn"]
        counts["attempts"] += 1
        if payload.get("tools") or payload.get("model") != meta["model"]:
            flags.append(f.name + ": unexpected tool or requested model")
        if turn in first_calls and turn not in seen and any(m["role"] == "assistant" for m in payload.get("messages", [])):
            flags.append(f.name + ": previous assistant in fresh session")
        if turn in original_prompts and turn not in seen:
            if payload.get("messages", [{}])[-1].get("content") != original_prompts[turn]:
                flags.append(f.name + ": unexpected user briefing")
        seen.add(turn)
        usage = reply.get("usage")
        if usage is None:
            counts["no_usage"] += 1
            continue
        if reply.get("model") != meta["model"]:
            flags.append(f.name + ": returned model differs")
        choice = reply["choices"][0]
        if meta.get("direct_response"):
            mode_set = (payload.get("thinking") == {"type": "disabled"} if meta["model"].startswith("deepseek")
                        else payload.get("chat_template_kwargs", {}).get("enable_thinking") is False and
                        payload.get("enable_thinking") is False)
            if not mode_set or choice["message"].get("reasoning_content") or usage.get("completion_tokens_details", {}).get("reasoning_tokens"):
                flags.append(f.name + ": direct-response mode not verified")
        counts["length_stops"] += choice.get("finish_reason") == "length"
        provider_text[turn].append(choice["message"].get("content") or "")
        identity = reply.get("id")
        if not identity or identity in ids:
            flags.append(f.name + ": missing or duplicate provider ID")
        ids.add(identity)
        counts["input"] += usage["prompt_tokens"]
        counts["output"] += usage["completion_tokens"]
        counts["peak_input"] = max(counts["peak_input"], usage["prompt_tokens"])
    for turn in scheduled:
        answer = final_result(run / "trace" / f"turn-{turn}.jsonl").strip()
        if answer not in (text.strip() for text in provider_text[turn]):
            flags.append(f"call {turn}: CLI output lacks matching provider reply")
    if seen != scheduled:
        flags.append("missing or unscheduled provider attempt")
    for row in result["rows"]:
        counts["missing_rows"] += row["actual"] is None
        counts["rows"] += 1
        for name, field in dependency_groups(season, row):
            labels[name][0] += int(row["actual"] is not None and row["actual"][field] == row["expected"][field])
            labels[name][1] += 1
    return {"score": result["total"], "groups": result["groups"], "counts": counts, "fields": labels,
            "flags": flags, "seed": meta["seed"], "variant": meta["variant"], "model": meta["model"],
            "edition": meta.get("edition", "original"), "direct_response": meta.get("direct_response", False), "level": meta["level"], "condition": meta["condition"]}


def compare(reports):
    by_seed = defaultdict(dict)
    configs = {(r["condition"], r["level"], r.get("direct_response", False), r.get("edition", "original")) for r in reports}
    if len(configs) != 1:
        raise ValueError("pair a single condition and level")
    for report in reports:
        key = report["variant"], report["model"]
        values = by_seed[report["seed"]]
        if key in values or report["flags"]:
            raise ValueError("duplicate or unverified run")
        values[key] = report["score"]
    ds, qw = [], []
    for values in by_seed.values():
        if len(values) != 4:
            raise ValueError("both models and both opening histories are required for each seed")
        ds.append(mean(values[v, "deepseek-v4-1-flash-261017"] for v in "AB"))
        qw.append(mean(values[v, "qwen3.8-flash"] for v in "AB"))
    gaps = [a-b for a,b in zip(ds,qw)]
    outcome = {"seeds": list(by_seed), "deepseek": mean(ds), "qwen": mean(qw), "gap": mean(gaps),
               "seed_gaps": gaps}
    if 2 <= len(gaps) <= 5:
        boot = sorted(mean(x) for x in product(gaps, repeat=len(gaps)))
        outcome["seed_bootstrap_95_pct"] = [boot[int(.025*len(boot))], boot[int(.975*len(boot))]]
    return outcome


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()
    records, invalid = [], []
    for run in args.runs:
        try:
            records.append(inspect(run))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            invalid.append({"run": str(run), "error": str(exc)})
    if invalid:
        print(json.dumps({"verified_records": records, "unscorable": invalid}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    print(json.dumps(compare(records) if args.compare else records, ensure_ascii=False, indent=2))
