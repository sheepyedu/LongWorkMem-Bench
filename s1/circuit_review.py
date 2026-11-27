"""Regrade each league circuit and summarize the measured context and memory dependencies."""

import argparse
import json
from pathlib import Path

from .circuit import Circuit, audit


def review(run):
    meta = json.loads((run / "manifest.json").read_text())
    if meta["status"] != "complete":
        raise ValueError(f"{run.name}: incomplete run")
    result = audit(run)
    saved = json.loads((run / "grade.json").read_text())
    if result["desks"] != saved["desks"] or result["total"] != saved["total"]:
        raise ValueError(f"{run.name}: stored grade does not match")
    circuit = Circuit(meta["seed"], meta["variant"], meta["desks"], meta["level"])
    stock_receipts = []
    changed = hits = historical = recovered = 0
    for turn, (desk, stage) in enumerate(circuit.schedule, 1):
        season = circuit.seasons[desk]
        orders = {team: season.stock[team] for team, _ in season.jobs.get(stage, [])}
        stock_receipts.append(circuit.receipt(turn, {"orders": orders}))
    lags = []
    for desk, details in result["desks"].items():
        season = circuit.seasons[desk]
        lags.append(
            circuit.schedule.index((desk, 8)) - circuit.schedule.index((desk, 1))
        )
        for row in details["rows"]:
            stock = season.stock[row["team"]]
            actual = row["actual"] or [None] * 4
            expected = row["expected"]
            for pair in (slice(0, 2), slice(2, 4)):
                if stock[pair] != expected[pair]:
                    changed += 1
                    hits += actual[pair] == expected[pair]
            if row["turn"] == 8:
                latest = season.expected(row["team"], "决赛")
                for i in range(4):
                    if latest[i] != expected[i]:
                        historical += 1
                        recovered += actual[i] == expected[i]
    usage = result["usage"]
    return dict(
        run=run.name,
        history=meta.get("history", "continuous"),
        turns=len(circuit.schedule),
        score=result["total"],
        groups=result["groups"],
        stock_only=circuit.score(stock_receipts)["total"],
        updated_pairs=[hits, changed],
        historical_fields=[recovered, historical],
        opening_to_audit_lag=[min(lags), max(lags)],
        **usage,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([review(p) for p in args.runs], ensure_ascii=False, indent=2))
