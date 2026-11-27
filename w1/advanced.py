"""Advanced W1 public releases, host-side reference run, and checkpoint grading."""
import argparse
import hashlib
import json
from pathlib import Path

from . import advanced_ledger, advanced_pay, advanced_mail
from .runstate import ROUNDS, freeze, prepare


DEPARTMENT_WEIGHTS = {"ledger": 40, "pay": 35, "mail": 25}


def weights(level, *, legacy=False):
    if level == 8 and not legacy:
        from .scorecard import OUTCOMES, PROCESS
        return {"process": sum(row[1] for row in PROCESS), "outcome": sum(row[2] for row in OUTCOMES)}
    if level in (7, 8):
        return {"ledger": 30, "pay": 25, "mail": 20, "memory": 25}
    return DEPARTMENT_WEIGHTS


def departments(level):
    if level in (1, 2):
        return {"ledger": advanced_ledger, "pay": advanced_pay, "mail": advanced_mail}
    if level == 3:
        from . import advanced_ledger_l3, advanced_pay_l3, advanced_mail_l3
        return {"ledger": advanced_ledger_l3, "pay": advanced_pay_l3, "mail": advanced_mail_l3}
    if level in (7, 8):
        from . import advanced_memory
        return {**departments(4), "memory": advanced_memory}
    if level in (4, 5, 6):
        from . import advanced_ledger_l4, advanced_pay_l4, advanced_mail_l4
        return {"ledger": advanced_ledger_l4, "pay": advanced_pay_l4, "mail": advanced_mail_l4}
    raise ValueError(f"Unknown advanced W1 level {level}")


def release(work, turn, variant, level, seed):
    if turn not in ROUNDS or variant not in {"A", "B"} or level not in {1, 2, 3, 4, 5, 6, 7, 8}:
        raise ValueError("Invalid W1 instance or turn")
    for folder in ("input", "inbox", "out"):
        (work / folder).mkdir(parents=True, exist_ok=True)
    prompts = [department.release(work, turn, variant, level, seed) for name, department in departments(level).items() if name != "memory"]
    prompt, = [prompt for prompt in prompts if prompt]
    if level >= 3 and turn == 3:
        prompt += " 请同时办理技术移交通知上随关账到期的薪酬档案。"
    if level >= 4 and turn in (2, 5, 6):
        prompt += " 请一并执行今日签发的核验函，并保留邮箱实际回执。"
    if level in (7, 8):
        from .advanced_memory import release as issue_mandate
        prompt += issue_mandate(work, turn, seed)
    if level in (5, 6, 7, 8):
        from .erp_window import notice
        prompt += notice(turn, level)
    return prompt


def public_digest(work, prompt):
    digest = hashlib.sha256(prompt.encode() + b"\0")
    for folder in ("input", "inbox"):
        for path in sorted((work / folder).rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(work)).encode() + b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_reference(run, variant, level, seed):
    work = prepare(run)
    turns = []
    for turn in ROUNDS:
        prompt = release(work, turn, variant, level, seed)
        for department in departments(level).values():
            department.reference(run, turn, variant, level, seed)
        freeze(run, turn)
        turns.append(dict(turn=turn, public_digest=public_digest(work, prompt)))
    manifest = dict(task="W1-advanced", status="complete", variant=variant, level=level,
                    seed=seed, reference=True, turns=turns)
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2))


def grade(run, variant=None, *, legacy=False, details=False):
    manifest = json.loads((run / "manifest.json").read_bytes())
    if manifest.get("task") != "W1-advanced" or manifest.get("status") != "complete" or manifest.get("smoke"):
        raise ValueError("A completed advanced W1 session is required")
    if variant is not None and variant != manifest["variant"]:
        raise ValueError("Requested variant differs from the frozen run")
    if [t["turn"] for t in manifest["turns"]] != list(ROUNDS):
        raise ValueError("Incomplete turn manifest")
    if any(not (run / "snapshots" / str(t)).is_dir() for t in ROUNDS):
        raise ValueError("Missing host snapshot")
    if not manifest.get("reference"):
        from .review import verify_office
        for turn in ROUNDS:
            verify_office(run / "trace" / f"turn-{turn}.jsonl")
    if manifest["level"] == 8 and not legacy:
        from .scorecard import summarize
        evidence = {}
        for label, department in departments(8).items():
            options = {"memory": {"whole_cases": True}, "pay": {"whole_rows": True}}.get(label, {})
            evidence.update(department.checks(run, manifest["variant"], 8, manifest["seed"], **options))
        items = summarize(evidence, details=details)
        return dict(scorer_version="w1-advanced/4", level=8, seed=manifest["seed"], variant=manifest["variant"],
                    max=100, total=round(sum(v["earned"] for v in items.values()), 4), items=items)
    items = {}
    for label, department in departments(manifest["level"]).items():
        weight = {**DEPARTMENT_WEIGHTS, "memory": 25}[label]
        factor = weights(manifest["level"], legacy=legacy)[label] / weight
        checks = department.checks(run, manifest["variant"], manifest["level"], manifest["seed"])
        if items.keys() & checks.keys() or sum(maximum for _, maximum, _ in checks.values()) != weight:
            raise ValueError("Invalid checkpoint weights or duplicate labels")
        for code, (earned, maximum, reason) in checks.items():
            if not 0 <= earned <= maximum:
                raise ValueError(f"Invalid score for {code}")
            items[code] = dict(department=label, earned=float(earned)*factor, max=maximum*factor, reason=reason)
    return dict(scorer_version="w1-advanced/3.4" if manifest["level"] >= 7 else "w1-advanced/2.1", variant=manifest["variant"],
                level=manifest["level"], seed=manifest["seed"],
                total=round(sum(item["earned"] for item in items.values()), 4), max=100, items=items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--reference", action="store_true")
    parser.add_argument("--legacy", action="store_true", help="Reproduce the archived calibration score")
    parser.add_argument("--details", action="store_true", help="Include underlying evidence for each checkpoint")
    parser.add_argument("--level", type=int, choices=[1, 2, 3, 4, 5, 6, 7, 8], default=8)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.reference:
        run_reference(args.run, "A", args.level, args.seed)
    print(json.dumps(grade(args.run, legacy=args.legacy, details=args.details), ensure_ascii=False, indent=2))
