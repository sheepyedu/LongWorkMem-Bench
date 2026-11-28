"""Objective S4 checkpoints, evaluated on the replay engine's complete event stream."""

import json

from .schedule import FILING_SHIFTS

VERSION = "s4-40-score-v2"


def player_trade(event):
    kind, value = event["action"], event["value"]
    if kind == "MARITIME_TRADE" and event["player"] == "You":
        return {value[-1]: 1}, sum(resource is not None for resource in value[:-1])
    if kind != "CONFIRM_TRADE":
        return None
    if event["player"] == "You":
        received, given = value["take"], value["give"]
    elif value["partner"] == "You":
        received, given = value["give"], value["take"]
    else:
        return None
    # Giving and receiving the same card cannot manufacture a delivery.
    net = {k: n - given.get(k, 0) for k, n in received.items() if n > given.get(k, 0)}
    return net, sum(given.values())


def distinct_keys(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("Duplicate JSON key")
    return obj


def filed_after_close(phase, rows, state):
    if not state:
        return False
    closed = False
    filed = None
    for r in rows:
        if r["phase"] != phase:
            continue
        result = r["result"]
        if result.get("event", {}).get("action") == "END_TURN":
            closed = True
        args = r["args"]
        if r["tool"] == "notes" and args.get("name") == phase and result.get("ok"):
            if args["op"] == "delete":
                filed = None
            elif args["op"] == "write":
                filed = args["text"] if closed else None
    if filed is None:
        return False
    try:
        data = json.loads(filed, object_pairs_hook=distinct_keys)
    except (TypeError, ValueError, RecursionError):
        return False
    return (
        isinstance(data, dict)
        and type(data.get("position")) in (int, float)
        and isinstance(data.get("hand"), dict)
        and all(type(x) in (int, float) for x in data["hand"].values())
        and data["position"] == state["position"]
        and data["hand"] == state["hand"]
    )


def reserve_window(phase):
    if phase.startswith("shift_"):
        return min((int(phase.split("_")[1]) - 1) // 3, 3)
    if phase == "amendment":
        return 1
    if phase in ("clearing", "receipt", "yard_opening", "yard"):
        return 4
    return 5


def grade(rows, states, events):
    # The runtime excludes setup and attributes every subsequent engine event once.
    trades = [
        (e, t) for e in events.get("clearing", ()) if (t := player_trade(e)) is not None
    ]
    received, cost = trades[0][1] if trades else ({}, None)
    cargo = next(iter(received)) if len(received) == 1 else "mixed" if trades else None
    correct_cargo = cargo == "BRICK"
    quantity = sum(received.values())
    terms = correct_cargo and quantity == 1 and cost is not None and 1 <= cost <= 4

    cities = [
        (phase, e)
        for phase, group in events.items()
        for e in group
        if e["player"] == "You" and e["action"] == "BUILD_CITY"
    ]
    city_phase, city = cities[0] if cities else (None, None)
    node = city["value"] if city else None
    authorized_city = node == 21 and city_phase == "commission"

    def decision(expected, actual, correct):
        return {
            "expected": expected,
            "actual": actual,
            "outcome": "correct"
            if correct
            else "wrong"
            if actual is not None
            else "unobserved",
        }

    decisions = {
        "cargo": decision("BRICK", cargo, correct_cargo),
        "city": decision(21, node, authorized_city),
    }
    decisions["city"].update(phase=city_phase, event=city["seq"] if city else None)
    decisions["cargo"].update(
        quantity=quantity, price=cost, event=trades[0][0]["seq"] if trades else None
    )
    completed = {
        phase
        for phase, group in events.items()
        if phase.startswith("shift_")
        and not phase.endswith("_opening")
        and any(e["player"] == "You" and e["action"] == "END_TURN" for e in group)
    }
    filings = {
        phase: filed_after_close(phase, rows, states.get(phase))
        for phase in (f"shift_{i}" for i in FILING_SHIFTS)
    }
    groups = [[] for _ in range(6)]
    for phase, group in events.items():
        groups[reserve_window(phase)].extend(group)
    progress_actions = {
        "ROLL",
        "BUILD_SETTLEMENT",
        "BUILD_CITY",
        "BUILD_ROAD",
        "BUY_DEVELOPMENT_CARD",
    }
    reserves = []
    for group in groups:
        progress = any(
            (e["player"] == "You" and e["action"] in progress_actions)
            or player_trade(e) is not None
            for e in group
        )
        breaches = [e["seq"] for e in group if e.get("wheat_after_spend", 2) < 2]
        reserves.append(
            {"points": 2 if progress and not breaches else 0, "breaches": breaches}
        )
    hand = states.get("market", {}).get("hand", {})
    checks = {
        "shifts": [round(12 * len(completed) / 15, 2), 12],
        "filings": [3 * sum(filings.values()), 12],
        "received": [16 if correct_cargo else 0, 16],
        "terms": [8 if terms else 0, 8],
        "capital_stock": [
            4 * min(hand.get("ORE", 0), 3) + 1.5 * min(hand.get("WHEAT", 0), 4),
            18,
        ],
        "city_work": [22 if authorized_city else 0, 22],
        "reserve": [sum(r["points"] for r in reserves), 12],
    }
    last = next(reversed(states.values()))
    return {
        "scoring_version": VERSION,
        "score": round(sum(x[0] for x in checks.values()), 2),
        "max": 100,
        "score_axis": "execution",
        "checks": checks,
        "authorization": {
            "correct": sum(d["outcome"] == "correct" for d in decisions.values()),
            "observed": sum(d["actual"] is not None for d in decisions.values()),
            "scheduled": 2,
            "decisions": decisions,
        },
        "filings": filings,
        "reserve_windows": reserves,
        "terminal": last["finished"],
        "own_turns": last["completed_own_turns"],
    }
