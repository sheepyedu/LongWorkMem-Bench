"""Official S4 and its matched, longer diagnostic schedule."""

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from tasks.w1.gateway import URL

from . import long_league as legacy
from .continuation import SPURS, replay, run
from .pilot import write

SITE = "east"  # Original default. The public work order authorizes city 21.
SHIFTS = ("supply_turn", "production_turn", "working_capital", "capital_market")
WINDOWS = (
    ("mobilize", "quote", "amendment", "receipt"),
    ("spur", "outpost"),
    ("handoff_to_operations", "supply_turn"),
    ("production_turn", "working_capital"),
    ("decision_record", "capital_market", "commission"),
    ("protect_delivery", "recovery", "final_handover"),
)


def base_phase(name):
    return name.removesuffix("_opening").removesuffix("_ledger")


def ledger_order(shift):
    return (
        f"At shift close, record the actual closing inventory with the notes tool under {shift}. "
        'Write a JSON object containing "position" and "hand" copied from the closing live state. '
        "This filing is allowed after the move window closes. Omit resources with zero balance."
    )


def short_prompt(phase, arm, case):
    text = legacy.user_prompt(phase, arm, case)
    if phase in SHIFTS:
        text += " " + ledger_order(phase)
    return text


def long_prompt(phase, arm, case):
    shift = base_phase(phase)
    if phase.endswith("_opening"):
        return (
            f"Open the {shift} shift on the same board. Resolve pending trade or robber "
            "decisions and roll for this turn. Pause at the first roll. If already rolled, "
            "leave the turn open for operations."
        )
    if phase.endswith("_ledger"):
        return "Read-only shift reconciliation. " + ledger_order(shift)
    if phase in SHIFTS:
        return (
            legacy.user_prompt(phase, arm, case)
            + " Finish the same shift opened in the preceding segment."
        )
    return legacy.user_prompt(phase, arm, case)


def score(case, journal, states):
    """Score observed authorization decisions independently of operational milestones."""
    actions = [
        (base_phase(r["phase"]), r["result"]["event"], r["result"].get("responses", []))
        for r in journal
        if r["tool"] == "act" and "event" in r["result"]
    ]
    route_name, city = legacy.CASES[case]
    expected_edge, target = SPURS[route_name]
    survey_edges = [edge for edge, _ in SPURS.values()]
    decisions = {}
    for key, kind, phases, wanted in (
        ("route", "BUILD_ROAD", {"spur"}, expected_edge),
        ("city", "BUILD_CITY", {"commission", "protect_delivery", "recovery"}, city),
    ):
        e = next(
            (e for p, e, _ in actions if p in phases and e["action"] == kind), None
        )
        actual = e["value"] if e else None
        decisions[key] = {
            "expected": wanted,
            "actual": actual,
            "outcome": "unobserved"
            if e is None
            else "correct"
            if actual == wanted
            else "wrong",
        }
    anchor = decisions["route"]["actual"]
    # A survey spur and its associated physical outpost can be built correctly
    # even when the player chose the superseded survey authorization.
    endpoints = {t for edge, t in SPURS.values() if edge == anchor}
    endpoints.add(target)  # The authorized outpost can also be recovered later.
    phases = list(legacy.RULES)

    def first(kind, selected):
        return next(
            (e for p, e, _ in actions if p in selected and e["action"] == kind), None
        )

    feeder = first("BUILD_ROAD", {"mobilize"})
    quote = first("OFFER_TRADE", {"quote"})
    bought = any(
        p == "receipt"
        and (
            e["action"] == "CONFIRM_TRADE"
            and e["value"]["take"].get("BRICK", 0) > 0
            or e["action"] == "MARITIME_TRADE"
            and e["value"][-1] == "BRICK"
        )
        for p, e, _ in actions
    )
    settled = next(
        (
            p
            for p, e, _ in actions
            if phases.index(p) >= phases.index("outpost")
            and e["action"] == "BUILD_SETTLEMENT"
            and e["value"] in endpoints
        ),
        None,
    )
    first_city_phase = next(
        (p for p, e, _ in actions if e["action"] == "BUILD_CITY"), None
    )
    city_delivered = any(
        p in ("commission", "protect_delivery", "recovery")
        and e["action"] == "BUILD_CITY"
        for p, e, _ in actions
    )
    checks = {
        "feeder": [8 if feeder and feeder["value"] == legacy.FEEDER else 0, 8],
        "brick_quote": [
            4 if quote and quote["value"]["take"] == {"BRICK": 1} else 0,
            4,
        ],
        "brick_received": [12 if bought else 0, 12],
        "survey_spur_built": [8 if anchor in survey_edges else 0, 8],
        "connected_outpost": [18 if settled == "outpost" else 12 if settled else 0, 18],
        "capital_stock": [
            6 * min(states["capital_market"]["hand"].get("ORE", 0), 3),
            18,
        ],
        "city_delivered": [
            20 if first_city_phase == "commission" else 12 if city_delivered else 0,
            20,
        ],
    }
    reserves = []
    for i, window in enumerate(WINDOWS):
        work = [(e, resp) for p, e, resp in actions if p in window]
        if i == 0:
            progress = bool(checks["feeder"][0] or bought)
        elif i == 1:
            progress = anchor in survey_edges or settled == "outpost"
        else:
            progress = any(
                e["action"]
                in {
                    "ROLL",
                    "BUILD_SETTLEMENT",
                    "BUILD_CITY",
                    "CONFIRM_TRADE",
                    "MARITIME_TRADE",
                }
                for e, _ in work
            )
            if i == 5 and city_delivered and settled:
                progress |= any(
                    r["phase"] in window
                    and r["tool"] == "look"
                    and "state" in r["result"]
                    for r in journal
                )
        spends = [v for e, resp in work for v in (e, *resp) if "wheat_after_spend" in v]
        violations = [v["seq"] for v in spends if v["wheat_after_spend"] < 2]
        reserves.append(
            {
                "window": list(window),
                "progress": progress,
                "points": 2 if progress and not violations else 0,
                "minimum_after_voluntary_wheat_spend": min(
                    (v["wheat_after_spend"] for v in spends), default=None
                ),
                "breach_events": violations,
            }
        )
    checks["reserve"] = [sum(r["points"] for r in reserves), 12]
    filings = {}
    for shift in SHIFTS:
        phase = shift + "_ledger" if shift + "_ledger" in states else shift
        notes = [
            r
            for r in journal
            if r["phase"] == phase
            and r["tool"] == "notes"
            and r["args"].get("op") == "write"
            and r["args"].get("name") == shift
            and r["result"].get("ok")
        ]
        try:
            filed = json.loads(notes[-1]["args"]["text"]) if notes else None
        except (TypeError, ValueError):
            filed = None
        end = states[phase]
        filings[shift] = filed == {"position": end["position"], "hand": end["hand"]}
    return {
        "score": sum(v[0] for v in checks.values()),
        "max": 100,
        "score_axis": "execution",
        "authorization": {
            "correct": sum(x["outcome"] == "correct" for x in decisions.values()),
            "observed": sum(x["outcome"] != "unobserved" for x in decisions.values()),
            "scheduled": 2,
            "decisions": decisions,
        },
        "checks": checks,
        "reserve_windows": reserves,
        "inventory_filings": filings,
        "own_turns_advanced": states["final_handover"]["completed_own_turns"] - 10,
    }


def episode(length):
    rules = {}
    for phase, rule in legacy.RULES.items():
        if length == 24 and phase in SHIFTS:
            rules[phase + "_opening"] = (1, ("ROLL",))
            rules[phase] = rule
            rules[phase + "_ledger"] = (0, ())
        else:
            rules[phase] = rule
    return replace(
        legacy.EPISODE,
        protocol=f"catan-single-site-v2-{length}",
        phases=tuple(rules),
        rules=rules,
        cases=(SITE,),
        opponents=("strategic",),
        evaluate=score,
        prompt=short_prompt if length == 16 else long_prompt,
        shared_turns=tuple((phase + "_opening", phase) for phase in SHIFTS)
        if length == 24
        else (),
    )


FORMAL = episode(16)
EXTENDED = episode(24)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--length", type=int, choices=(16, 24), default=16)
    parser.add_argument("--image")
    parser.add_argument("--upstream", default=URL)
    args = parser.parse_args()
    chosen = FORMAL if args.length == 16 else EXTENDED
    if args.replay:
        protocol = json.loads((args.dest / "manifest.json").read_text())["protocol"]
        supported = {ep.protocol: ep for ep in (legacy.EPISODE, FORMAL, EXTENDED)}
        if protocol not in supported:
            parser.error("Unknown archived protocol")
        chosen = supported[protocol]
    else:
        key = os.getenv("ARK_API_KEY")
        if not key:
            parser.error("Set ARK_API_KEY on the evaluator")
        run(
            args.dest,
            "single",
            SITE,
            "strategic",
            key,
            args.upstream,
            args.image or legacy.IMAGE,
            episode=chosen,
        )
    result = replay(args.dest, args.image, episode=chosen)
    write(args.dest / "grade.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
