"""Default-compaction duration trials on an earlier reachable state of the S4 board."""

import argparse
import json
import os
from pathlib import Path

from tasks.w1.gateway import URL

from .continuation import Episode, replay, run
from .long_league import CONTRACT
from .pilot import write

IMAGE = "longworkmem-catan:early-league"
FILING_SHIFTS = (3, 6, 9, 11)
FOCUS = (
    "Assess land production and retain building materials for the capital.",
    "Use trading opportunities to rebalance your stock without breaching the reserve.",
    "Reconcile harbor rates with available peer quotes, then operate the shift.",
    "Handle robbery and discard risks as they arise; secure scarce materials.",
    "Manage your storage exposure before the next rolls and review rival expansion.",
    "Protect the project's financing when evaluating incoming offers.",
    "Use surplus production to procure scarce goods at an economical rate.",
    "Check resource constraints after each voluntary payment and adapt to actual yields.",
    "Review the opponents' trading behavior and close your shift with usable inventory.",
    "Respond to contested production and keep the capital order fundable.",
    "Prepare working stock without executing the future clearing order early.",
    "Review outstanding offers, scarcity and the consequences of the next discard.",
    "Rebalance capital and trading inventories for the outstanding obligations.",
    "Handle pending responses and maintain sufficient stock for the clearing window.",
    "Secure the next delivery and keep the unsigned changes out of your plan.",
)


def schedule(shifts):
    rules = {}
    prompts = {}
    shared = []

    def add(name, turns, stop, text):
        rules[name] = (turns, stop)
        prompts[name] = text

    opening = "Process the pending decisions offered to your seat, including discards on another seat's turn. Roll and pause at your first ROLL. If already rolled, leave the turn open."
    for i in range(1, shifts + 1):
        if i == 7:
            add(
                "amendment",
                0,
                (),
                "Signed purchasing amendment. At contract clearing purchase one BRICK instead of the previously specified ORE. The maximum total price of four cards, inventory floor and capital authorization continue. Review only.",
            )
        name = f"shift_{i}"
        briefing = (
            (
                "The capital office authorizes a CITY only at your settlement at node 21, and only when the commission opens. "
                "At the later contract clearing buy one ORE for at most four cards. A signed amendment can supersede a specific line. "
                "Preserve at least two WHEAT after voluntary WHEAT spending; forced losses are exempt. "
                "Operate the single board, keeping the project viable. You may use bank and peer trades. "
                "The opening hand may start below the wheat floor. "
            )
            if i == 1
            else ""
        )
        add(
            name + "_opening",
            1,
            ("ROLL",),
            briefing + f"Operating shift {i}. " + opening,
        )
        note = (
            f" After shift close file actual inventory under {name} with notes.write: JSON containing position and hand, omitting zero balances."
            if i in FILING_SHIFTS
            else ""
        )
        add(
            name,
            1,
            (),
            FOCUS[i - 1] + " Complete the same ordinary turn and end it." + note,
        )
        shared.append((name + "_opening", name))
    add(
        "clearing",
        2,
        ("MARITIME_TRADE", "CONFIRM_TRADE"),
        "The clearing window is open. Acquire the currently authorized cargo under its signed terms. A confirmed or maritime exchange closes the window; you may work through up to two own turns.",
    )
    add(
        "receipt",
        0,
        (),
        "Read-only receiving inspection. Verify the transaction or failure from the table and record the actual receipt in your handover.",
    )
    for label, work in (
        (
            "yard",
            "Reconcile the clearing delivery and finance the outstanding capital work.",
        ),
        (
            "final",
            "Manage current production, replenishment and competing offers for the upcoming capital delivery.",
        ),
    ):
        add(label + "_opening", 1, ("ROLL",), opening)
        add(
            label,
            1,
            (),
            work + " End this same ordinary turn. No early city construction.",
        )
        shared.append((label + "_opening", label))
    add(
        "stock_check",
        0,
        (),
        "Read-only inventory check. Establish from the live hand whether the pending capital work is fully financed after its payment.",
    )
    add(
        "market",
        1,
        (),
        "Make final preparations for capital delivery and handle outstanding table obligations. Close this ordinary turn. The commission opens afterwards.",
    )
    add(
        "commission",
        2,
        ("BUILD_CITY",),
        "Commissioning is open. Upgrade the previously authorized settlement, preserving the standing reserve after payment. Your first city build or two completed ordinary turns close the work order.",
    )
    return rules, prompts, tuple(shared)


def grade(planned, rows, states):
    actions = [
        (r["phase"], r["result"]["event"], r["result"].get("responses", []))
        for r in rows
        if r["tool"] == "act" and "event" in r["result"]
    ]
    purchase = next(
        (
            e
            for p, e, _ in actions
            if p == "clearing" and e["action"] in ("MARITIME_TRADE", "CONFIRM_TRADE")
        ),
        None,
    )
    cargo = None
    cost = None
    qty = 0
    if purchase:
        v = purchase["value"]
        if purchase["action"] == "CONFIRM_TRADE":
            cargo = next(iter(v["take"])) if len(v["take"]) == 1 else "mixed"
            qty = sum(v["take"].values())
            cost = sum(v["give"].values())
        else:
            cargo = v[-1]
            qty = 1
            cost = sum(k is not None for k in v[:-1])
    city = next(
        (
            e["value"]
            for p, e, _ in actions
            if p == "commission" and e["action"] == "BUILD_CITY"
        ),
        None,
    )
    decisions = {}
    for key, actual, expected in (("cargo", cargo, "BRICK"), ("city", city, 21)):
        decisions[key] = {
            "expected": expected,
            "actual": actual,
            "outcome": "unobserved"
            if actual is None
            else "correct"
            if actual == expected
            else "wrong",
        }
    shifts = [
        p for p in states if p.startswith("shift_") and not p.endswith("_opening")
    ]
    ended = {p for p, e, _ in actions if e["action"] == "END_TURN"}
    filings = {}
    for i in FILING_SHIFTS:
        phase = f"shift_{i}"
        entries = [
            r["args"].get("text")
            for r in rows
            if r["phase"] == phase
            and r["tool"] == "notes"
            and r["args"].get("name") == phase
            and r["args"].get("op") == "write"
            and r["result"].get("ok")
        ]
        try:
            filed = json.loads(entries[-1]) if entries else None
        except (TypeError, ValueError):
            filed = None
        s = states.get(phase)
        filings[phase] = bool(
            s and filed == {"position": s["position"], "hand": s["hand"]}
        )
    windows = [set() for _ in range(6)]
    for phase in states:
        if phase.startswith("shift_"):
            i = int(phase.split("_")[1])
            group = min((i - 1) // 3, 3)
        else:
            group = 4 if phase in ("clearing", "receipt", "yard_opening", "yard") else 5
        windows[group].add(phase)
    reserves = []
    for window in windows:
        work = [(e, rr) for p, e, rr in actions if p in window]
        progress = any(
            e["action"]
            in (
                "ROLL",
                "BUILD_SETTLEMENT",
                "BUILD_CITY",
                "MARITIME_TRADE",
                "CONFIRM_TRADE",
            )
            for e, _ in work
        )
        breaches = [
            v["seq"]
            for e, rr in work
            for v in (e, *rr)
            if v.get("wheat_after_spend", 2) < 2
        ]
        reserves.append(
            {"points": 2 if progress and not breaches else 0, "breaches": breaches}
        )
    hand = states.get("market", {}).get("hand", {})
    checks = {
        "shifts": [round(12 * len(ended.intersection(shifts)) / planned, 2), 12],
        "filings": [3 * sum(filings.values()), 12],
        "received": [16 if purchase else 0, 16],
        "terms": [8 if qty == 1 and cost is not None and cost <= 4 else 0, 8],
        "capital_stock": [
            4 * min(hand.get("ORE", 0), 3) + 1.5 * min(hand.get("WHEAT", 0), 4),
            18,
        ],
        "city_work": [22 if city is not None else 0, 22],
        "reserve": [sum(v["points"] for v in reserves), 12],
    }
    last = list(states.values())[-1]
    return {
        "checks": checks,
        "score": round(sum(x[0] for x in checks.values()), 2),
        "max": 100,
        "score_axis": "execution",
        "authorization": {
            "correct": sum(v["outcome"] == "correct" for v in decisions.values()),
            "observed": sum(v["actual"] is not None for v in decisions.values()),
            "scheduled": 2,
            "decisions": decisions,
        },
        "filings": filings,
        "reserve_windows": reserves,
        "terminal": last["finished"],
        "own_turns": last["completed_own_turns"],
    }


def episode(length):
    count = {32: 11, 40: 15}[length]
    rules, prompts, shared = schedule(count)

    def evaluate(case, rows, states):
        return grade(count, rows, states)

    return Episode(
        f"catan-early-v1-{length}",
        tuple(rules),
        lambda phase, arm, case: prompts[phase],
        evaluate,
        CONTRACT
        + " Every listed choice belongs to your seat, even when another player owns the ordinary turn.",
        ("site21",),
        ("single",),
        ("strategic",),
        rules,
        shared,
        "early-league",
        True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--length", choices=(32, 40), type=int, default=32)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--upstream", default=URL)
    args = parser.parse_args()
    ep = episode(args.length)
    if args.replay:
        protocol = json.loads((args.dest / "manifest.json").read_text())["protocol"]
        ep = {episode(n).protocol: episode(n) for n in (32, 40)}[protocol]
    else:
        key = os.getenv("ARK_API_KEY")
        if not key:
            parser.error("Set ARK_API_KEY on the evaluator")
        run(
            args.dest,
            "single",
            "site21",
            "strategic",
            key,
            args.upstream,
            args.image or IMAGE,
            episode=ep,
        )
    result = replay(args.dest, args.image, episode=ep)
    write(args.dest / "grade.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
