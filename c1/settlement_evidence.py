"""Export one evidence row per planned settlement deadline from saved run grades."""

import argparse
import csv
import json
from pathlib import Path
import sys

from .review import audit
from .settlement import NAMES


def milestones(checks, name):
    prefixes = [name + ".", "lineage." + name + "."]
    if name == "close":
        prefixes += ["archive.", "lineage.archive-", "rerun."]
    selected = {
        k: v for k, v in checks.items() if any(k.startswith(p) for p in prefixes)
    }
    return (
        round(sum(v[0] for v in selected.values()), 3),
        round(sum(v[1] for v in selected.values()), 3),
        " ".join(k for k, v in selected.items() if v[0] < v[1]),
    )


def round_rows(run, score):
    run = Path(run)
    m = json.loads((run / "manifest.json").read_text())
    review = audit(run)
    nrounds = 7 if m["level"] == 3 else 6
    failed = review["shell_failures"]
    calls = {}
    for receipt in sorted((run / "trace").glob("api-*.json")):
        packet = json.loads(receipt.read_bytes())
        calls.setdefault(packet["turn"], []).append(packet["n"])
    retries = {row["receipt"]: row for row in review["retry_attempts"]}
    for turn, name in enumerate((*NAMES, "guarantee")[:nrounds], 1):
        ids = calls.get(turn, [])
        metrics = review["turns"].get(turn, {})
        result = dict(
            cohort=run.parent.name,
            model=m["model"],
            seed=m["seed"],
            variant=m["variant"],
            status=m["status"],
            round=turn,
            job=name,
            first_request=min(ids, default=None),
            last_request=max(ids, default=None),
            requests=len(ids),
            shell_calls=metrics.get("tools", 0),
            shell_nonzero=sum(z["turn"] == turn and "status" in z for z in failed),
            client_rejections=sum(
                z["turn"] == turn and "client_error" in z for z in failed
            ),
            retries=sum(f"api-{i:04}.json" in retries for i in ids),
            compactions=metrics.get("compactions", 0),
            peak_input=metrics.get("peak_input", 0),
        )
        for where, directory in (("dispatch", "dispatch"), ("repaired", "snapshots")):
            applicable = where == "repaired" or "dispatch" in score
            section = score.get(where, score)
            got, possible, missed = (
                milestones(section["checks"], name)
                if applicable
                else (None, None, None)
            )
            result[where + "_file"] = (
                (run / directory / str(turn) / "out" / (name + ".json")).is_file()
                if applicable
                else None
            )
            result[where + "_score"] = got
            result[where + "_max"] = possible
            result[where + "_misses"] = missed
        yield result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--score-name", default="settlement-score-v2.json")
    args = parser.parse_args()
    writer = None
    for run in args.runs:
        score = json.loads((run / args.score_name).read_text())
        for row in round_rows(run, score):
            if writer is None:
                writer = csv.DictWriter(
                    sys.stdout, fieldnames=list(row), lineterminator="\n"
                )
                writer.writeheader()
            writer.writerow(row)


if __name__ == "__main__":
    main()
