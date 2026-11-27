"""Host accounting for the final three dated guarantee cuts."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import tempfile

from . import reserve
from .grade_evidence import content


def expected(seed, authority, requests):
    terms = defaultdict(dict)
    for bulletin in reserve.notices(seed).values():
        for entry in bulletin:
            terms[entry["desk"], entry["band"]][entry["start"]] = entry
    ordered = sorted(
        {r["id"]: r for r in requests}.values(), key=lambda r: (r["day"], r["seq"])
    )
    result = {name: [] for name in ("decisions", "posted", "balance")}
    for cut in reserve.CUTS:
        occupied = Counter()
        for r in ordered:
            if r["day"] > cut:
                break
            key = r["desk"], r["band"]
            starts = [start for start in terms[key] if start <= r["day"]]
            term = terms[key][max(starts)] if starts else None
            if not term or term["end"] < r["day"]:
                status = "expired"
            elif term["channel"] != r["channel"]:
                status = "channel"
            elif authority != r["signer"]:
                status = "signature"
            elif occupied[key] + r["amount"] > term["limit"]:
                status = "capacity"
            else:
                status = "posted"
                occupied[key] += r["amount"]
                result["posted"].append([cut, *key, r["id"], r["amount"]])
            result["decisions"].append([cut, r["id"], status])
        result["balance"].extend([cut, *key, v] for key, v in occupied.items())
    return result


def grade_phase(snap, seed, variant, approvers, probes, checks, differences=None):
    from .settlement_grade import load_output, matches, describe_fields

    authority = approvers[0 if variant == "A" else 1]

    def evaluate(got, want, cut, field):
        if not isinstance(got, dict) or not isinstance(got.get(field), list):
            return False
        rows = got[field]
        if any(
            not isinstance(row, list)
            or not row
            or type(row[0]) is not int
            or row[0] not in reserve.CUTS
            for row in rows
        ):
            return False
        return matches(
            [r for r in rows if r[0] == cut], [r for r in want[field] if r[0] == cut]
        )

    want = expected(seed, authority, reserve.requests(seed, *approvers, 0))
    got = load_output(snap, "guarantee")
    if differences is not None:
        describe_fields(differences, "guarantee", got, want)
    for cut in reserve.CUTS:
        for field, weight in (("decisions", 3), ("posted", 2), ("balance", 2)):
            checks[f"guarantee.{cut}.{field}"] = [
                weight * evaluate(got, want, cut, field),
                weight,
            ]
    with (
        probes.workspace(snap) as work,
        tempfile.TemporaryDirectory(dir=work / "scratch") as tmp,
    ):
        root = Path(tmp)
        batches = reserve.requests(seed, *approvers, 97)
        (root / "guarantees.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in batches)
        )
        (root / "guarantee-contract.txt").write_text(reserve.FORMAT)
        location = root.relative_to(work)
        dest = location / "receipt.json"
        err = probes.command(work, f"python3 project/reserve.py {location} {dest}")
        try:
            got = json.loads(content(work, dest))
        except (ValueError, OSError, RecursionError):
            got = None
        want = expected(seed, authority, batches)
        if differences is not None:
            describe_fields(differences, "guarantee.rerun", got, want)
            if err:
                differences["guarantee.rerun.execution"] = err
        ok = not err and all(matches(got, want, f) for f in want)
        checks["guarantee.rerun"] = [4 * ok, 4]
