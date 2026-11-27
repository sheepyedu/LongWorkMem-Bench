"""Compare paired runs and isolate audit decisions affected by the R2 handover."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from .settlement import release
from .settlement_grade import ledger, load_output


def audit_map(value):
    rows = value.get("audit") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return {}
    decisions = {}
    for row in rows:
        if (
            isinstance(row, list)
            and len(row) == 2
            and all(isinstance(v, str) for v in row)
        ):
            key, decision = row
            decisions[key] = decision if key not in decisions else None
    return decisions


def authority_reversals(directory, seed, level, snapshot_dir="snapshots"):
    expected, actual = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        for variant in ("A", "B"):
            work = Path(tmp) / variant
            for turn in range(1, 6):
                release(work, turn, variant, seed, level)
            inp = work / "input"
            plan = json.loads((inp / "jobs/corrections.json").read_text())
            expected[variant] = dict(ledger(inp, plan)["audit"])
            actual[variant] = audit_map(
                load_output(
                    directory / f"{seed}-{variant}" / snapshot_dir / "5", "corrections"
                )
            )
    changed = [k for k in expected["A"] if expected["A"][k] != expected["B"][k]]
    counts = {
        v: sum(actual[v].get(k) == expected[v][k] for k in changed) for v in expected
    }
    return {
        "changed": len(changed),
        "correct": counts,
        "both_correct": sum(
            all(actual[v].get(k) == expected[v][k] for v in expected) for k in changed
        ),
    }


def guarantee_reversals(directory, seed):
    from .reserve import requests
    from .reserve_grade import expected
    from .settlement import generate

    approvers = generate(seed, 2, "A")[3]
    batch = requests(seed, *approvers, 0)
    oracle = [
        {
            (cut, eid): status
            for cut, eid, status in expected(seed, signer, batch)["decisions"]
        }
        for signer in approvers
    ]
    changed = [key for key in oracle[0] if oracle[0][key] != oracle[1][key]]
    outcomes = {"changed": len(changed)}
    for snapshot in ("dispatch", "snapshots"):
        paired = []
        for variant in ("A", "B"):
            data = load_output(
                directory / f"{seed}-{variant}" / snapshot / "7", "guarantee"
            )
            decisions = {}
            rows = data.get("decisions") if isinstance(data, dict) else None
            for row in rows if isinstance(rows, list) else ():
                if (
                    isinstance(row, list)
                    and len(row) == 3
                    and type(row[0]) is int
                    and isinstance(row[1], str)
                    and isinstance(row[2], str)
                ):
                    key = row[0], row[1]
                    decisions[key] = row[2] if key not in decisions else None
            paired.append(decisions)
        outcomes[snapshot] = sum(
            all(actual.get(key) == want[key] for actual, want in zip(paired, oracle))
            for key in changed
        )
    return outcomes


def released_material(run, turn):
    source = run / "snapshots" / str(turn) / "input"
    result = {
        p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source.rglob("*")
        if p.is_file()
    }
    result["__user_prompt__"] = hashlib.sha256(
        (run / "trace" / f"prompt-{turn}.txt").read_bytes()
    ).hexdigest()
    return result


def compare(a, b, seeds, score_name):
    rows, memory, guarantees = [], [], []
    for seed in seeds:
        for variant in ("A", "B"):
            manifests, grades = [], []
            for folder in (a, b):
                run = folder / f"{seed}-{variant}"
                manifest = json.loads((run / "manifest.json").read_text())
                if (manifest["seed"], manifest["variant"]) != (seed, variant):
                    raise ValueError(f"Wrong pairing at {run}")
                manifests.append(manifest)
                score = json.loads((run / score_name).read_text())
                grades.append(score["total"] if score["valid"] else None)
            for field in (
                "level",
                "limit",
                "dispatch_window",
                "image",
                "claude",
                "source_hashes",
            ):
                if manifests[0].get(field) != manifests[1].get(field):
                    raise ValueError(
                        f"Paired inputs differ at {seed}-{variant}: {field}"
                    )
            if manifests[0]["session"] == manifests[1]["session"]:
                raise ValueError("Compared runs share a session")
            count = min(len(m["turns"]) for m in manifests)
            for turn in range(1, count + 1):
                if released_material(
                    a / f"{seed}-{variant}", turn
                ) != released_material(b / f"{seed}-{variant}", turn):
                    raise ValueError(f"Inputs differ at {seed}-{variant} turn {turn}")
            rows.append(
                {
                    "seed": seed,
                    "variant": variant,
                    "scores": grades,
                    "verified_turns": count,
                }
            )
        if manifests[0]["level"] == 3:
            guarantees.append([guarantee_reversals(folder, seed) for folder in (a, b)])
        memory.append(
            [
                authority_reversals(folder, seed, manifests[0]["level"])
                for folder in (a, b)
            ]
        )
    complete = all(None not in row["scores"] for row in rows)
    means = (
        [sum(row["scores"][i] for row in rows) / len(rows) for i in (0, 1)]
        if complete
        else None
    )
    return {
        "rows": rows,
        "means": means,
        "gap": means[0] - means[1] if means else None,
        "r5_reversals": memory,
        "r7_reversals": guarantees,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--seeds", nargs="+", required=True, type=int)
    parser.add_argument("--score-name", default="settlement-score-v2.json")
    args = parser.parse_args()
    print(
        json.dumps(
            compare(args.left, args.right, args.seeds, args.score_name), indent=2
        )
    )
