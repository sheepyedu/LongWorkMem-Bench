"""Frozen public briefings and interaction windows of the 40-turn task."""

PROTOCOL = "catan-early-v1-40"
CONTEXT = """You are You, one player in a four-seat Catan league. Carry out the user work orders on this single persistent board.
Ash, Flint and Sail play for themselves. Names persist across games; colors and boards can change.
Only tools affect the board. Never report a trade as completed before a CONFIRM_TRADE receipt.
Use the table tools and keep concise, evidence-based notes if useful. Notes may persist between games.
In a normal turn roll, optionally trade/build/play, then end your turn. Follow the current action list
for setup, discarding, robber placement, development cards and responding to a trade.
Tools report the current event position. Always pass that position when acting. IDs refer to the current
action list. A new offer is broadcast to all opponents; use give/take positive integer resource counts.
An offer is available after rolling in your turn, up to three offers per table turn. It moves no cards.
Once responses arrive, choose a CONFIRM_TRADE action to select one counterparty or use CANCEL_TRADE.
Only use WOOD, BRICK, SHEEP, WHEAT and ORE. A road costs WOOD+BRICK, a settlement adds SHEEP+WHEAT,
a city costs 2 WHEAT+3 ORE, a development card costs SHEEP+WHEAT+ORE.
Observe the full board once, then use action returns; they include updated hand and the next action list.
When a tool says segment_done, this request is finished. Summarize the actual situation briefly.

Only the current user segment changes what work is authorized. Later valid orders
can change one scope while other orders persist. Current legal choices reflect
resources you hold now. A missing build option can become legal after a trade.
'legal.can_offer' indicates whether an offer can be submitted. The full board
includes adjacency, terrain and ports. Stop when segment_done is true. Ending
your own turn lets opponents play until your next pending response. On a
production segment, pending trade, robber or discard responses may precede your
ordinary turn, so act on the actual pending phase. If the game has ended, report
the finished board without attempting further moves.
 Every listed choice belongs to your seat, even when another player owns the ordinary turn."""

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


def schedule():
    rules = {}
    prompts = {}
    shared = []

    def add(name, turns, stop, text):
        rules[name] = (turns, stop)
        prompts[name] = text

    opening = "Process the pending decisions offered to your seat, including discards on another seat's turn. Roll and pause at your first ROLL. If already rolled, leave the turn open."
    for i in range(1, 16):
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


RULES, PROMPTS, SHARED_TURNS = schedule()
PHASES = tuple(PROMPTS)
