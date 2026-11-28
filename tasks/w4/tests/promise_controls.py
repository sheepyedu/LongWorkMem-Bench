"""Offline comparisons: same old evidence with two rubrics; new contracts with new plays."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.w4.quota.promise_score import scorecard
from tasks.w4.quota.score import score
from tasks.w4.tests.quota_controls import play


def summary(atoms, metrics):
    return {"points": round(sum(a["earned"] for a in atoms), 4), **metrics}


def compare():
    archive = (
        Path(__file__).resolve().parents[3]
        / "rollout/w4/deepseek-v4.1-flash/v4/grade.json"
    )
    original = json.loads(archive.read_text())
    rows = []

    def retrospective(name, g):
        atoms, metrics = scorecard(g["atoms"])
        rows.append(
            {
                "task": "v4 original evidence",
                "strategy": name,
                "frozen": g["total"],
                **summary(atoms, metrics),
            }
        )

    retrospective("published DeepSeek", original)
    with TemporaryDirectory() as td:
        for edition in ("old", "new"):
            modes = [
                "gold",
                "latest",
                "opening",
                "arrival",
                "ignore_feedback",
                "recover",
                "empty",
            ]
            if edition == "new":
                modes += ["ignore_transfer", "always_add", "all_or_wait"]
            for mode in modes:
                d = Path(td) / (edition + mode)
                play(d, mode, promise=edition == "new")
                g = score(d)
                if edition == "old":
                    retrospective(mode, g)
                else:
                    rows.append(
                        {
                            "task": "v4.2 new work",
                            "strategy": mode,
                            **summary(g["atoms"], g["fulfilment"]),
                        }
                    )
    return rows


if __name__ == "__main__":
    print(json.dumps(compare(), ensure_ascii=False, indent=2))
