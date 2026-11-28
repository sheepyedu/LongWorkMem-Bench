"""Compare independent repeated sessions within identical instance and protocol cells."""

import argparse
import csv
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict


def analyze(rows, near):
    cells = defaultdict(dict)
    required = ("task", "instance", "condition", "model", "run", "status")
    statuses = {"complete", "participant_failure", "infra_error", "budget_stop"}
    for i, row in enumerate(rows, 2):
        if any(not (row.get(k) or "").strip() for k in required) or not isinstance(
            row.get("score"), str
        ):
            raise ValueError(f"row {i}: incomplete identity/status/score schema")
        task, instance, condition, model, run, status = [
            row[k].strip() for k in required
        ]
        if status not in statuses:
            raise ValueError(f"row {i}: unknown status")
        cell = cells[(task, instance, condition)].setdefault(model, {})
        if run in cell:
            raise ValueError(f"row {i}: duplicate run")
        value = None
        if status in {"complete", "participant_failure"}:
            value = float(row["score"])
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"row {i}: invalid score")
        elif row["score"].strip():
            raise ValueError(
                f"row {i}: store partial progress outside the official score"
            )
        cell[run] = status, value
    if not cells:
        raise ValueError("empty input")
    result = []
    for (task, instance, condition), models in sorted(cells.items()):
        stats, pairs = {}, []
        for model, runs in sorted(models.items()):
            values = [v for _, v in runs.values() if v is not None]
            data = dict(
                n=len(values),
                attempts=len(runs),
                statuses=dict(Counter(s for s, _ in runs.values())),
            )
            if values:
                avg = statistics.mean(values)
                lo, hi = min(values), max(values)
                data.update(
                    mean=avg,
                    minimum=lo,
                    maximum=hi,
                    down=lo - avg,
                    up=hi - avg,
                    span=hi - lo,
                    variance=statistics.variance(values) if len(values) > 1 else None,
                    sd=statistics.stdev(values) if len(values) > 1 else None,
                    near_ceiling=sum(v >= near for v in values) / len(values),
                    near_floor=sum(v <= 100 - near for v in values) / len(values),
                )
            stats[model] = data
        for a, b in itertools.combinations(stats, 2):
            x, y = stats[a], stats[b]
            if not x["n"] or not y["n"]:
                continue
            gap = x["mean"] - y["mean"]
            # Repeats share the business instance, not necessarily paired sampling noise.
            se = (
                math.sqrt(x["sd"] ** 2 / x["n"] + y["sd"] ** 2 / y["n"])
                if min(x["n"], y["n"]) >= 2
                else None
            )
            pairs.append(
                dict(
                    a=a,
                    b=b,
                    mean_a_minus_b=gap,
                    independent_repeat_se=se,
                    observed_gap_min=x["minimum"] - y["maximum"],
                    observed_gap_max=x["maximum"] - y["minimum"],
                )
            )
        result.append(
            dict(
                task=task,
                instance=instance,
                condition=condition,
                models=stats,
                contrasts=pairs,
            )
        )
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("csv")
    cli.add_argument(
        "--near",
        type=float,
        default=95,
        help="Descriptive near-ceiling threshold (default 95)",
    )
    args = cli.parse_args()
    if not 50 < args.near <= 100:
        cli.error("--near must be in (50,100]")
    try:
        with open(args.csv, newline="", encoding="utf-8-sig") as source:
            print(
                json.dumps(
                    analyze(csv.DictReader(source), args.near),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    except (OSError, ValueError, TypeError, csv.Error) as exc:
        cli.exit(2, f"Invalid calibration data: {exc}\n")
