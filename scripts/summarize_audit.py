"""Recompute range and asymmetric deviations of each four-instance historical sample."""
import csv
from decimal import Decimal
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1] / "docs/results/advanced-audit-20261127"


def describe(values):
    center, low, high = mean(values), min(values), max(values)
    return (center, low, high, low-center, high-center)


def write_stage_deviations(samples, seeds):
    """Subtract each stage's four-instance mean; weighted stages already use total-score units."""
    groups = {}
    with (ROOT / "stages.csv").open() as source:
        for row in csv.DictReader(source):
            key = row["task"], row["model"], row["group"]
            seed = int(row["seed"])
            group = groups.setdefault(key, {})
            if seed in group:
                raise ValueError(f"duplicate stage: {key}, {seed}")
            group[seed] = Decimal(row["earned"])

    totals = dict.fromkeys(samples, Decimal(0))
    with (ROOT / "stage-deviations.csv").open("w", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["task", "model", "seed", "group", "earned", "group_mean", "deviation"])
        for (task, model, group), values in sorted(groups.items()):
            if values.keys() != set(seeds):
                raise ValueError(f"incomplete stage: {task}, {model}, {group}")
            center = mean(values.values())
            for seed in seeds:
                value = values[seed]
                totals[task, model, seed] += value
                writer.writerow([task, model, seed, group, value, center, value - center])
    for key, total in totals.items():
        # C1 rounds both panels and their composite. stages.csv retains six decimals.
        if abs(total - samples[key][-1]) > Decimal("0.011"):
            raise ValueError(f"stages do not reconstruct the published score for {key}")


def main():
    with (ROOT / "runs.csv").open() as source:
        rows = list(csv.DictReader(source))
    samples = {}
    for row in rows:
        inputs, output, score = (Decimal(row[k]) for k in ("input", "output", "score"))
        key = row["task"], row["model"], int(row["seed"])
        if key in samples:
            raise ValueError(f"duplicate instance: {key}")
        samples[key] = (inputs, output, inputs+output, score)
    seeds = (17217, 17219, 17231, 17239)
    write_stage_deviations(samples, seeds)
    with (ROOT / "dispersion.csv").open("w", newline="") as dest:
        writer = csv.writer(dest, lineterminator="\n")
        writer.writerow(["task","model_or_paired_difference","metric","mean","min","max","min_minus_mean","max_minus_mean"])
        for task in ("W1","C1","S1"):
            ds = [samples[task,"DeepSeek",s] for s in seeds]
            qw = [samples[task,"Qwen",s] for s in seeds]
            gap = [tuple(x-y for x,y in zip(a,b)) for a,b in zip(ds,qw)]
            for label, sample in (("DeepSeek", ds), ("Qwen", qw), ("DeepSeek-Qwen",gap)):
                for metric, values in zip(("input","output","input+output","score"),zip(*sample)):
                    writer.writerow([task,label,metric,*describe(values)])


if __name__ == "__main__":
    main()
