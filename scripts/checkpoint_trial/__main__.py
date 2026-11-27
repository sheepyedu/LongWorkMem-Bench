"""Recompute granularity-1 on all 24 retained runs. No model or model API is involved."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean, stdev

from .scoring import c1_score, s1_score, w1_score

REFERENCE = Path(__file__).resolve().parents[2] / "docs/results/advanced-audit-20261127/runs.csv"


def write_summary(path, rows):
    metrics = ("original", "granular", "format_only", "format_and_granular",
               "s1_changed_field", "s1_format_and_changed_field")
    with path.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["task", "model", "rule", "n", "mean", "min", "max", "range", "sample_sd"])
        for task in ("W1", "C1", "S1"):
            for model in ("DeepSeek", "Qwen"):
                group = [r for r in rows if (r["task"], r["model"]) == (task, model)]
                for key in metrics:
                    values = [float(r[key]) for r in group if r[key] != ""]
                    if values:
                        low, high = min(values), max(values)
                        writer.writerow([task, model, key, len(values), round(mean(values),6),
                                         low, high, round(high-low,6), round(stdev(values),6)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, help="original batch with status/ and frozen workspaces")
    parser.add_argument("output", type=Path, help="separate output directory")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    details = {}
    rows = []
    with REFERENCE.open() as f:
        reference = list(csv.DictReader(f))
    for orig in reference:
        task, model, seed, arm = (orig[k] for k in ("task","model","seed","variant"))
        name = f"{task.lower()}-{model.lower()}-{seed}-{arm}"
        meta = json.loads((args.batch/"status"/(name+".json")).read_text())
        run = args.batch/meta["run"]
        manifest = json.loads((run/"manifest.json").read_text())
        if (manifest["seed"],manifest["variant"],manifest["status"],manifest["model"]) != (
                int(seed),arm,orig["status"],meta["model"]):
            raise ValueError(f"instance mismatch: {name}")
        old,new,parts = {"W1":w1_score,"C1":c1_score,"S1":s1_score}[task](run,manifest)
        if old != float(orig["score"]) or not 0 <= new <= 100:
            raise ValueError(f"score reconciliation failed: {name}")
        details[name] = parts
        rows.append(dict(task=task,model=model,seed=seed,variant=arm,status=manifest["status"],
                         original=old,granular=round(new,4),delta=round(new-old,4) or 0.0,
                         format_only=parts.get("format_only",""),format_and_granular=parts.get("both",""),
                         s1_changed_field=parts.get("changed_field_only",""),
                         s1_format_and_changed_field=parts.get("format_and_changed_field","")))
        print(name, old, round(new,4), flush=True)
    if len(details)!=24:
        raise ValueError("incomplete cohort")
    with (args.output/"scores.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_summary(args.output/"summary.csv", rows)
    (args.output/"components.json").write_text(json.dumps(details,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    main()
