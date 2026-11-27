"""Run and independently regrade the S1 equipment-relay memory calibration."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from w1.claude import run_claude
from w1.gateway import Gateway, MODEL, URL
from .pilot import write
from .relay import CONTINUOUS, HANDOVER, RULES, WEIGHTS, Season, decode, grade, submit


def final_result(path):
    terminal = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    results = [e for e in terminal if e.get("type") == "result" and not e.get("is_error")]
    if len(results) != 1:
        raise ValueError("missing successful Claude result")
    return results[0]["result"]


def evaluate(run):
    meta = json.loads((run / "manifest.json").read_text())
    if meta["status"] != "complete":
        raise ValueError("incomplete run")
    season = Season(meta["seed"], meta["level"], meta["variant"])
    received, note = {}, ""
    for row in meta["turns"]:
        turn = row["turn"]
        command = {}
        for index in row["calls"]:
            response = final_result(run / "trace" / f"turn-{index}.jsonl")
            try:
                candidate = decode(response)
                submit(season, turn, candidate, note)
            except ValueError:
                continue
            command = candidate
            break
        receipt = submit(season, turn, command, note)
        frozen = json.loads((run / f"receipt-{turn}.json").read_text())
        if frozen != receipt:
            raise ValueError(f"R{turn}: stored booking differs from submitted command")
        received[str(turn)] = receipt
        note = receipt["note"]
        if meta["condition"] in ("current", "evidence"):
            note = ""
    full = meta["condition"] in ("relay", "continuous")
    required = list(range(1, 9)) if full else list(WEIGHTS)
    if [r["turn"] for r in meta["turns"]] != required:
        raise ValueError("incomplete sequence")
    return grade(season, received)


def run_one(dest, model, level, seed, arm, condition, direct_response=False):
    season = Season(seed, level, arm)
    run = dest / f"L{level}-{seed}-{arm}-{model}-{condition}"
    run.mkdir(parents=True, exist_ok=False, mode=0o700)
    (run / "trace").mkdir()
    remote_name = MODEL if model == "deepseek" else "qwen3.8-flash"
    key = os.environ["ARK_API_KEY" if model == "deepseek" else "DEEPSEEK_API_KEY"]
    url = URL if model == "deepseek" else os.environ["DEEPSEEK_BASE_URL"].rstrip("/") + "/chat/completions"
    meta = {"status": "running", "model": remote_name, "variant": arm, "seed": seed,
            "level": level, "condition": condition, "turns": [], "request_limit": 32, "transport_timeout_seconds": 600,
            "direct_response": direct_response,
            "git": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True).strip(),
            "cli": subprocess.check_output(["claude", "--version"], text=True).strip()}
    write(run / "manifest.json", meta)
    cold = condition in ("current", "evidence")
    note = ""
    try:
        with tempfile.TemporaryDirectory(prefix="league-desk-") as tmp, Gateway(
                key, run, 32, allowed=(), model=remote_name, url=url, timeout=600, direct_response=direct_response,
                private_markers=(str(run.resolve()), ".claude-manager/", "s1/relay.py")) as gateway:
            desk = Path(tmp)
            (desk / "desk").mkdir()
            for turn in (list(WEIGHTS) if cold else range(1, 9)):
                new_session = cold or turn == 1 or (condition == "relay" and turn in (4, 7, 8))
                if new_session:
                    session = str(uuid.uuid4())
                originals = [t for t in season.bulletins if t < turn] if condition == "evidence" else []
                prompt = season.prompt(turn, note, condition, originals)
                context = RULES + ("本班为独立受理，只依现有记录办理。" if cold else
                                   HANDOVER if condition == "relay" else CONTINUOUS)
                (run / "trace" / f"prompt-{turn}.txt").write_text(prompt)
                calls = []
                for index in (turn, turn + 8):
                    calls.append(index)
                    run_claude(run, index, gateway, session, prompt, desk,
                               config={"mcpServers": {}}, context=context, allowed=(),
                               first_session=new_session and index == turn)
                    try:
                        cmd = decode(final_result(run / "trace" / f"turn-{index}.jsonl"))
                        receipt = submit(season, turn, cmd, note)
                        break
                    except ValueError as exc:
                        prompt = "单据格式未接收：" + str(exc) + "。请重新提交本班完整单据。"
                else:
                    receipt = submit(season, turn, {}, note)
                write(run / f"receipt-{turn}.json", receipt)
                note = "" if cold else receipt["note"]
                meta["turns"].append({"turn": turn, "session": session, "calls": calls})
                write(run / "manifest.json", meta)
        meta["status"] = "complete"
        write(run / "manifest.json", meta)
        result = evaluate(run)
        write(run / "grade.json", result)
        print(run.name, result["total"], flush=True)
    except Exception as exc:
        meta.update(status="error", error=str(exc).replace(key, "[redacted]"))
        write(run / "manifest.json", meta)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest", type=Path)
    p.add_argument("--models", nargs="+", choices=["deepseek", "qwen"], default=["deepseek", "qwen"])
    p.add_argument("--seeds", nargs="+", type=int, required=True)
    p.add_argument("--variants", nargs="+", choices=["A", "B"], default=["A", "B"])
    p.add_argument("--level", choices=range(1, 5), type=int, required=True)
    p.add_argument("--condition", choices=["relay","continuous","current","evidence"], default="relay")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--direct-response", action="store_true", help="disable provider thinking for both models")
    args = p.parse_args()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(run_one, args.dest.resolve(), model, args.level, seed, arm, args.condition, args.direct_response)
                for seed in args.seeds for arm in args.variants for model in args.models]
        for job in jobs:
            job.result()


if __name__ == "__main__":
    main()
