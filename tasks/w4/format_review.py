"""Diagnostic replay for a narrowly defined expanded '当时应发' audit cell."""

import json
import sys
from pathlib import Path
from .grade import OBJECTS, grade, norm, sheets
from .scenario import address, object_id


def review(run, raw=None):
    if raw is None:
        raw = grade(run)
    sheet = sheets(run / "snapshots/11/交接.xlsx")[0].get("追溯", {})
    original = next(
        d
        for d in raw["details"]
        if d["turn"] == 11
        and d["group"] == "追溯"
        and any(k.endswith("/当时应发") for k in d["checks"])
    )
    recovered = []
    for key, c in original["checks"].items():
        if c["ok"] or not key.endswith("/当时应发"):
            continue
        case = key.split("/")[0]
        i, s = OBJECTS[case]
        fields = norm(sheet.get(case, {}).get("当时应发", "")).split("|")
        email = address(i)
        if (
            len(fields) == 3
            and fields[0] in (email, email.split("@")[0] + "@")
            and fields[1] == object_id(i, s)
            and norm(fields[2]) == c["expected"]
        ):
            recovered.append(case)
    delta = original["weight"] * len(recovered) / len(original["checks"])
    return dict(
        frozen=raw["total"],
        eligible_expanded_claims=recovered,
        delta=round(delta, 6),
        sensitivity_total=round(sum(d["earned"] for d in raw["details"]) + delta, 4),
    )


if __name__ == "__main__":
    print(json.dumps(review(Path(sys.argv[1])), ensure_ascii=False, indent=2))
