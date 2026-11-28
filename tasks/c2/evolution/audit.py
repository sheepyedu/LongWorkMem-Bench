"""Reconcile the experiment records on the host, including the actual model inputs."""

import argparse
import json
from pathlib import Path
from tasks.c2.audit import audit
from .scenario import PROMPTS, CHANNELS


def examine(run, scores):
    from tasks.c2.cohorts import scenario as cohort

    customer_run = scores.get("version") == cohort.SCORING_REVISION
    report = audit(
        run,
        prompts=cohort.PROMPTS if customer_run else PROMPTS,
        channels=CHANNELS,
        injected={(8, "C", "handover-C-Q29" if customer_run else "C-resume-08")},
    )
    private = set(scores["items"] if customer_run else scores["checks"]) | {
        "tasks/c2/cohorts/grade",
        "tasks.c2.cohorts.grade",
        "tasks/c2/cohorts/reference",
        "tasks/c2/cohorts/oracle",
        "tasks/c2/evolution/grade",
        "tasks.c2.evolution.grade",
        "tasks/c2/evolution/case_grade",
        "tasks.c2.evolution.case_grade",
        "tasks/c2/evolution/reference",
        "tasks/c2/evolution/oracle",
        "tasks.c2.evolution.oracle",
    }
    for path in sorted((run / "trace").glob("api-*.json")):
        record = json.loads(path.read_bytes())
        wire = json.dumps(record.get("request", {}), ensure_ascii=False)
        leaked = sorted(key for key in private if key in wire)
        if leaked:
            report["flags"].append(
                [path.name, "internal scoring identifiers in request", leaked]
            )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("grade", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            examine(args.run, json.loads(args.grade.read_text())),
            ensure_ascii=False,
            indent=2,
        )
    )
