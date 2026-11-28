"""One persistent Catan board with staged work orders and delayed authorizations."""

from .continuation import FEEDER, SPURS, Episode
from .public import CONTEXT

IMAGE = "longworkmem-catan:long-league"
PROTOCOL = "catan-long-league-v1"
CASES = {
    "east": ("east", 21),
    "east-capital": ("east", 46),
}
OPPONENTS = ("cautious", "strategic")
RULES = {
    "mobilize": (1, ("BUILD_ROAD",)),
    "quote": (1, ("OFFER_TRADE",)),
    "amendment": (0, ()),
    "receipt": (1, ("CONFIRM_TRADE", "MARITIME_TRADE")),
    "spur": (1, ("BUILD_ROAD",)),
    "outpost": (1, ("BUILD_SETTLEMENT",)),
    "handoff_to_operations": (1, ()),
    "supply_turn": (1, ()),
    "production_turn": (1, ()),
    "working_capital": (1, ()),
    "decision_record": (0, ()),
    "capital_market": (1, ()),
    "commission": (2, ("BUILD_CITY",)),
    "protect_delivery": (1, ()),
    "recovery": (2, ()),
    "final_handover": (0, ()),
}
CONTRACT = (
    CONTEXT.split("A practice position")[0].replace(
        "Win each full match by playing it.",
        "Carry out the user work orders on this single persistent board.",
    )
    + """
Only the current user segment changes what work is authorized. Later valid orders
can change one scope while other orders persist. Current legal choices reflect
resources you hold now. A missing build option can become legal after a trade.
'legal.can_offer' indicates whether an offer can be submitted. The full board
includes adjacency, terrain and ports. Stop when segment_done is true. Ending
your own turn lets opponents play until your next pending response. On a
production segment, pending trade, robber or discard responses may precede your
ordinary turn, so act on the actual pending phase. If the game has ended, report
the finished board without attempting further moves.
"""
)


def user_prompt(phase, _arm, case):
    _, capital = CASES[case]
    return {
        "mobilize": (
            "Open the work order by laying feeder road [16,21]. The first road ends this segment. "
            "Survey register: west spur [6,23] leads to settlement node 6; east spur [23,52] leads "
            "to settlement node 52. The current authorization is west. When the capital commission "
            f"later opens, the only approved city upgrade is the existing settlement at node {capital}. "
            "Maintain a floor of two WHEAT after any voluntary use of WHEAT throughout this work order. "
            "Forced discards and losses from other players are exempt. Do not build a city before commissioning."
        ),
        "quote": (
            "Request a peer quote to buy one additional BRICK for the outpost; save materials needed "
            "to pay for both the spur and settlement. This segment stops after submitting a quote. "
            "Do not consummate a sale before the next order."
        ),
        "amendment": (
            "Signed survey decision: the east survey entry supersedes the west route "
            "and its endpoint. The capital and inventory orders are outside this amendment. Review only."
        ),
        "receipt": (
            "Review the outstanding offer and complete the needed brick purchase if terms are viable. "
            "You may submit an alternative when there is no useful acceptance. A confirmed exchange "
            "or maritime purchase pauses the segment. Check what actually arrived."
        ),
        "spur": (
            "Lay the currently authorized spur. The first road closes this construction segment. "
            "Use the work order and signed decisions to identify the target."
        ),
        "outpost": (
            "Complete the currently authorized outpost settlement. You can fix missing materials "
            "through a legal trade. The first settlement or the end of your turn closes the segment."
        ),
        "handoff_to_operations": (
            "Turn the site over to production. Check the outpost remains in service, respond to "
            "immediate game obligations, and finish the current ordinary turn. Start budgeting for "
            "the later approved upgrade. No city construction yet."
        ),
        "supply_turn": (
            "Operate through one own turn. Accumulate ORE for the capital works through legal "
            "production or economical trades. Keep the existing reserve active. No city construction yet."
        ),
        "production_turn": (
            "Advance one own turn through ordinary play. Handle robber, discard and incoming offers as "
            "they arrive. Consider how choices change the capital materials and risks. No city construction yet."
        ),
        "working_capital": (
            "Use one own turn to prepare the city materials. Avoid consuming resources the "
            "signed capital order and reserve still need. No city construction yet."
        ),
        "decision_record": (
            "Read-only decision record. A request to change the capital target and relax the reserve "
            "was denied. The previously signed capital target and reserve are still in force."
        ),
        "capital_market": (
            "Use one final own turn to stage materials for the capital commission. Handle any "
            "pending responses and close out the turn. The city may only be built after commissioning."
        ),
        "commission": (
            "The capital commission is now open. Upgrade the previously authorized settlement; "
            "the first city build pauses work. You have up to two own turns for this window. "
            "Account for the active reserve after payment."
        ),
        "protect_delivery": (
            "Operate one more own turn. Preserve delivery and resolve in-game pressure, "
            "including incoming offers, forced discards and the robber. The reserve remains active."
        ),
        "recovery": (
            "Use up to two own turns to repair any still deliverable original work. A changed "
            "board does not authorize a substitute outpost or city. If the work is already done, "
            "verify the result without unnecessary trades or construction."
        ),
        "final_handover": (
            "Read-only final handover. Verify the live feeder, spur, outpost, city, and hand, "
            "and report which parts of the work order were delivered."
        ),
    }[phase]


def evaluate(case, journal, states):
    route, city = CASES[case]
    edge, outpost = SPURS[route]
    rows = [r for r in journal if r["tool"] == "act" and "event" in r["result"]]
    by_phase = {phase: [r for r in rows if r["phase"] == phase] for phase in RULES}

    def is_action(r, action, value=None):
        e = r["result"]["event"]
        return e["action"] == action and (value is None or e["value"] == value)

    def buys_brick(r):
        after = r["result"]["event"]
        return (
            is_action(r, "CONFIRM_TRADE")
            and after["value"]["take"].get("BRICK", 0) > 0
            or is_action(r, "MARITIME_TRADE")
            and after["value"][-1] == "BRICK"
        )

    def reserve_credit(window, max_points):
        spent = [
            e
            for r in window
            for e in [r["result"]["event"], *r["result"].get("responses", [])]
            if "wheat_after_spend" in e
        ]
        breaches = [e["seq"] for e in spent if e["wheat_after_spend"] < 2]
        return [max_points if spent and not breaches else 0, max_points], breaches

    feeder = next((r for r in by_phase["mobilize"] if is_action(r, "BUILD_ROAD")), None)
    quotes = [r for r in by_phase["quote"] if is_action(r, "OFFER_TRADE")]
    spur = next((r for r in by_phase["spur"] if is_action(r, "BUILD_ROAD")), None)
    placed_outpost = next(
        (r["phase"] for r in rows if is_action(r, "BUILD_SETTLEMENT", outpost)), None
    )
    cities = [r for r in rows if is_action(r, "BUILD_CITY")]
    placed_city = next(
        (r["phase"] for r in cities if is_action(r, "BUILD_CITY", city)), None
    )
    on_time_city = bool(
        cities
        and cities[0]["phase"] == "commission"
        and is_action(cities[0], "BUILD_CITY", city)
    )
    recovery_city = placed_city in {"commission", "protect_delivery", "recovery"}
    boundary = list(RULES).index("handoff_to_operations")
    early_phases = set(list(RULES)[:boundary])
    early_reserve, early_breaches = reserve_credit(
        [r for r in rows if r["phase"] in early_phases], 10
    )
    late_reserve, late_breaches = reserve_credit(
        [r for r in rows if r["phase"] not in early_phases], 14
    )
    checks = {
        "feeder": [8 if feeder and is_action(feeder, "BUILD_ROAD", FEEDER) else 0, 8],
        "quote": [
            4
            if quotes and quotes[0]["result"]["event"]["value"]["take"] == {"BRICK": 1}
            else 0,
            4,
        ],
        "brick_received": [
            8 if any(buys_brick(r) for r in by_phase["receipt"]) else 0,
            8,
        ],
        "current_spur": [12 if spur and is_action(spur, "BUILD_ROAD", edge) else 0, 12],
        "outpost": [
            12
            if placed_outpost == "outpost"
            else 8
            if placed_outpost and placed_outpost not in early_phases
            else 0,
            12,
        ],
        "capital_stock": [
            4 * min(states["capital_market"]["hand"].get("ORE", 0), 3),
            12,
        ],
        "authorized_city": [20 if on_time_city else 12 if recovery_city else 0, 20],
        "reserve_construction": early_reserve,
        "reserve_operations": late_reserve,
    }
    return {
        "score": sum(v[0] for v in checks.values()),
        "max": 100,
        "checks": checks,
        "first_spur": spur["result"]["event"]["value"] if spur else None,
        "first_city": cities[0]["result"]["event"]["value"] if cities else None,
        "outpost_phase": placed_outpost,
        "city_phase": placed_city,
        "voluntary_reserve_breaches": early_breaches + late_breaches,
        "own_turns_advanced": states["final_handover"]["completed_own_turns"] - 10,
        "game_terminal": states["final_handover"]["finished"],
    }


EPISODE = Episode(
    PROTOCOL,
    tuple(RULES),
    user_prompt,
    evaluate,
    CONTRACT,
    tuple(CASES),
    ("single",),
    OPPONENTS,
    RULES,
)


def main():
    from .single_site import main as official_main

    official_main()


if __name__ == "__main__":
    main()
