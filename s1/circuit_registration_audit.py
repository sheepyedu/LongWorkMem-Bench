"""Measure the effect of an explicit phase label on the registration score."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .circuit import Circuit, REGISTER_PHASE, audit, final_result, read_command


def compare(run):
    official = audit(run)
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("score_version") != 2 or manifest.get("parser_version") != 3:
        raise ValueError("Expected circuit score version 2 and parser version 3")
    circuit = Circuit(
        manifest["seed"], manifest["variant"], manifest["desks"], manifest["level"],
        manifest["qualifiers"],
    )
    receipts = []
    formats = Counter()
    changed = []
    for turn, (desk, stage) in enumerate(circuit.schedule, 1):
        receipt = json.loads((run / f"receipt-{turn}.json").read_text())
        receipts.append(receipt)
        if stage not in REGISTER_PHASE:
            continue
        call = manifest["calls"][turn - 1][-1]
        path = Path("trace") / f"turn-{call}.jsonl"
        try:
            reply = read_command(final_result(run / path), 3)
        except ValueError:
            reply = {}
        rows = reply.get("register", {})
        phase = REGISTER_PHASE[stage]
        for team in circuit.register_teams(desk, stage):
            row = rows.get(team) if isinstance(rows, dict) else None
            if isinstance(row, list):
                formats["array"] += 1
                continue
            if row is None:
                formats["absent"] += 1
                continue
            if (not isinstance(row, dict) or set(row) != {phase}
                    or not isinstance(row[phase], list) or len(row[phase]) != 4
                    or not all(type(value) in (int, str) for value in row[phase])):
                formats["other"] += 1
                continue
            formats["one exact phase wrapper"] += 1
            accepted = circuit.receipt(turn, {"register": {team: row[phase]}})
            receipt["register"][team] = accepted["register"][team]
            changed.append({"turn": turn, "desk": desk, "team": team, "source": str(path)})
    alternative = circuit.score(receipts)
    if official["outcome_points"] != alternative["outcome_points"]:
        raise ValueError("Orders changed during the registration-only comparison")
    return {
        "official": official["total"], "alternative": alternative["total"],
        "official_registration": official["registration_points"],
        "alternative_registration": alternative["registration_points"],
        "order_points": official["outcome_points"], "formats": formats, "changes": changed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    print(json.dumps(compare(parser.parse_args().run), ensure_ascii=False, indent=2))
