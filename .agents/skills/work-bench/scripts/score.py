"""Score host-normalized business snapshots against a private, versioned contract."""

import argparse
import json
from fractions import Fraction
from pathlib import Path


def unique(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError(
            "duplicate JSON key; preserve occurrences before normalization"
        )
    return obj


def load(path):
    def invalid(value):
        raise ValueError(f"invalid JSON number: {value}")

    return json.loads(
        Path(path).read_text(), object_pairs_hook=unique, parse_constant=invalid
    )


def same_value(a, b):
    # Object order has no business meaning. Ordered sequences and field types survive.
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(
        b, sort_keys=True, allow_nan=False
    )


def score(contract, evidence):
    version = contract["version"]
    if not isinstance(version, str) or not version or evidence["version"] != version:
        raise ValueError("unmatched scoring contract")
    groups = contract["groups"]
    observations = evidence["groups"]
    if (
        not isinstance(groups, dict)
        or not isinstance(observations, dict)
        or groups.keys() != observations.keys()
    ):
        raise ValueError("missing or unexpected observation group")
    total = Fraction(0)
    weight_sum = 0
    details = {}
    for name, group in groups.items():
        weight, want, got = group["weight"], group["expected"], observations[name]
        if (
            type(weight) is not int
            or weight <= 0
            or not isinstance(want, dict)
            or not want
        ):
            raise ValueError(f"{name}: invalid weight or empty scoring population")
        if not isinstance(got, dict):
            raise ValueError(f"{name}: no valid host observation")
        missing = sorted(want.keys() - got.keys())
        extra = sorted(got.keys() - want.keys())
        wrong = sorted(
            k for k in want.keys() & got.keys() if not same_value(want[k], got[k])
        )
        hits = len(want) - len(missing) - len(wrong)
        points = Fraction(weight * hits, len(want) + len(extra))
        details[name] = dict(
            hits=hits,
            denominator=len(want) + len(extra),
            missing=missing,
            extra=extra,
            wrong=wrong,
            earned=float(points),
            weight=weight,
        )
        total += points
        weight_sum += weight
    if weight_sum != 100:
        raise ValueError("group weights must sum to 100")
    return dict(version=version, score=float(total), groups=details)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("contract")
    cli.add_argument("evidence")
    args = cli.parse_args()
    try:
        print(
            json.dumps(
                score(load(args.contract), load(args.evidence)),
                ensure_ascii=False,
                indent=2,
            )
        )
    except (KeyError, ValueError, TypeError, OSError) as exc:
        cli.exit(2, f"Unscorable: {exc}\n")
