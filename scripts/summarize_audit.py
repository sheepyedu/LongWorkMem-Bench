"""Recompute range and asymmetric deviations of each four-instance historical sample."""
import csv
from decimal import Decimal
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1] / "docs/results/advanced-audit-20261127"


def describe(values):
    center, low, high = mean(values), min(values), max(values)
    return (center, low, high, low-center, high-center)


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
