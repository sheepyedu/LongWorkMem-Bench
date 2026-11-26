"""Compare completed, equally provisioned DeepSeek and Qwen W1 sessions on matched instances."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from statistics import mean

from .advanced import grade
from .gateway import MODEL
from .review import events, summarize
from .runstate import ROUNDS


QWEN = "qwen3.8-flash"
MODELS = (MODEL, QWEN)
STAGES = {"ledger": 40, "pay": 35, "mail": 25}
HOLDOUT_SEEDS = {1733, 2671}
HARNESS = ("gateway.py", "pilot.py", "office.py", "mail.py", "runstate.py")


def require(condition, run, reason):
    if not condition:
        raise ValueError(f"{run}: {reason}")


def read_manifest(run):
    m = json.loads((run / "manifest.json").read_bytes())
    require(m.get("task") == "W1-advanced" and m.get("status") == "complete"
            and not m.get("reference") and not m.get("smoke"), run, "expected a completed advanced model run")
    require(m.get("model") in MODELS and m.get("variant") in ("A", "B"), run, "unexpected model or variant")
    require(type(m.get("seed")) is int and type(m.get("level")) is int and m["level"] > 0,
            run, "missing instance seed or level")
    require(m.get("backend") == "docker" and all(isinstance(m.get(k), str) and m[k].strip()
            for k in ("session", "docker_image", "claude")), run, "missing Docker or Claude session metadata")
    require(m.get("isolation", {}).get("status") == 0, run, "office isolation was not verified")
    turns = m.get("turns", [])
    require([r.get("turn") for r in turns] == list(ROUNDS), run, "expected nine ordered completed rounds")
    require(all(type(r.get("upstream_calls")) is int and r["upstream_calls"] > 0 and
                re.fullmatch(r"[0-9a-f]{64}", r.get("public_digest", "")) for r in turns),
            run, "missing round request count or public material digest")
    require(type(m.get("limit")) is int and sum(r["upstream_calls"] for r in turns) <= m["limit"],
            run, "invalid request budget")
    hashes = m.get("file_hashes", {})
    require(isinstance(hashes, dict) and all(re.fullmatch("[0-9a-f]{64}", hashes.get(k, "")) for k in HARNESS),
            run, "missing harness file digests")
    return m


def completed_receipts(run, manifest):
    model = manifest["model"]
    review = summarize(run)
    for field in ("missing_request_files", "request_record_issues", "turn_record_issues"):
        require(not review[field], run, f"{field}: {review[field][:2]}")
    require(not review["exposed_score_reports"], run, "host score report in office messages")
    require(review["models"] == [model], run, "provider model differs from declared model")
    missing_usage = set(review["attempts_without_usage"])
    retries, waiting = [], defaultdict(list)
    trace = run / "trace"
    prompt_hashes = []
    for turn in ROUNDS:
        totals = review["turns"][turn]
        require(totals.get("successful", 0) > 0 and totals["attempts"] == totals["expected_attempts"],
                run, f"R{turn} lacks complete request evidence")
        prompt_hashes.append(hashlib.sha256((trace / f"prompt-{turn}.txt").read_bytes()).hexdigest())
        log = trace / f"turn-{turn}.jsonl"
        terminal = [e for _, e in events(log) if e and e["type"] == "result"]
        require(len(terminal) == 1 and terminal[0].get("subtype") == "success"
                and terminal[0].get("is_error") is False and terminal[0].get("session_id") == manifest["session"],
                run, f"R{turn} lacks a successful Claude terminal result for this session")
    for path in sorted(trace.glob("api-*.json")):
        row = json.loads(path.read_bytes())
        payload = row.get("request")
        require(isinstance(payload, dict) and payload.get("model") == model and payload.get("messages"),
                run, f"{path.name} upstream request/model missing")
        status, turn = row.get("status"), row["turn"]
        require(type(status) is int and isinstance(row.get("end"), (float, int)), run, f"{path.name} incomplete attempt")
        if path.name in missing_usage:
            retryable = status in (408, 409, 425, 429) or 500 <= status < 600
            require(retryable and row.get("error") and not row.get("response"), run,
                    f"{path.name} missing usage without documented transient failure")
        else:
            reply = row.get("response", {})
            require(200 <= status < 300 and not row.get("error") and reply.get("model") == model
                    and (reply.get("id") or row.get("request_id")) and reply.get("choices"),
                    run, f"{path.name} incomplete successful upstream receipt")
        if waiting or path.name in missing_usage:
            # A later success in the same round is not sufficient unless it replays the failed work.
            wire = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
            key = turn, hashlib.sha256(wire).digest()
            if path.name in missing_usage:
                waiting[key].append((row["n"], status))
            else:
                for failed, code in waiting.pop(key, []):
                    retries.append(dict(turn=turn, failed_attempt=failed, status=code, successful_attempt=row["n"]))
    require(not waiting, run, "transient failure had no later matching successful retry in the same round")
    usage = dict(review["observed_usage"])
    usage["attempts"] = sum(t["attempts"] for t in review["turns"].values())
    return {"usage": usage, "retries": retries,
            "private_markers_in_requests": review["private_markers_in_requests"]}, prompt_hashes


def compare(paths):
    groups, sessions = defaultdict(dict), set()
    for path in paths:
        run = Path(path)
        m = read_manifest(run)
        key = m["level"], m["seed"], m["variant"]
        require(m["session"] not in sessions and m["model"] not in groups[key], run, "duplicate session or model for instance")
        sessions.add(m["session"])
        groups[key][m["model"]] = (run, m)
    if not groups or len({level for level, _, _ in groups}) != 1:
        raise ValueError("Compare one nonempty difficulty level at a time")
    splits = {"holdout" if seed in HOLDOUT_SEEDS else "development" for _, seed, _ in groups}
    if len(splits) != 1:
        raise ValueError("Compare development and holdout instances separately")
    cohort = None
    result = []
    for (level, seed, variant), group in sorted(groups.items()):
        if set(group) != set(MODELS):
            raise ValueError(f"Level {level}, seed {seed}, {variant}: missing model for paired comparison")
        model_stats = {}
        expected_inputs = None
        for model in MODELS:
            run, m = group[model]
            environment = m["docker_image"], m["claude"], m["limit"], tuple(m["file_hashes"][k] for k in HARNESS)
            if cohort is None:
                cohort = environment
            require(environment == cohort, run, "image, Claude version, request budget or office harness differs across runs")
            review, prompts = completed_receipts(run, m)
            inputs = ([r["public_digest"] for r in m["turns"]], prompts)
            require(expected_inputs is None or inputs == expected_inputs, run, "round materials or prompts differ within pair")
            expected_inputs = inputs
            assessment = grade(run)
            stages = {s: round(sum(row["earned"] for code, row in assessment["items"].items()
                                   if code.split(".", 1)[0] == s), 4) for s in STAGES}
            model_stats[model] = {"run": str(run), "stages": stages, "total": assessment["total"],
                                  "scorer_version": assessment["scorer_version"], **review}
        gap = model_stats[MODEL]["total"] - model_stats[QWEN]["total"]
        result.append({"seed": seed, "variant": variant, "models": model_stats, "paired_gap":round(gap, 4)})
    means = {}
    for model in MODELS:
        runs = [pair["models"][model] for pair in result]
        means[model] = {"total":round(mean(r["total"] for r in runs), 4),
                        "stages":{s:round(mean(r["stages"][s] for r in runs), 4) for s in STAGES},
                        "attempts":sum(r["usage"]["attempts"] for r in runs),
                        "requests_with_usage":sum(r["usage"]["successful"] for r in runs)}
    return {"level": level, "split": splits.pop(), "pair_count": len(result), "stage_maxima": STAGES,
            "docker_image": cohort[0], "claude": cohort[1], "request_limit": cohort[2], "pairs": result,
            "model_means": means, "mean_paired_gap": round(mean(p["paired_gap"] for p in result), 4)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="Completed model run directories, in any order")
    args = parser.parse_args()
    try:
        summary = compare(args.runs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
