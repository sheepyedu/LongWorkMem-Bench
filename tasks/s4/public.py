"""Instructions issued to players and the schedule of their visible assignments."""

CONTEXT = """You are You, one player in a four-seat Catan league. Win each full match by playing it.
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
A practice position starts from a supplied frozen midgame board. Play only the current turn;
the league will open the next position after you end the turn. Practice positions have independent hands.
Follow any earlier assignment for that practice table."""
 
PRACTICE = {
    "transfer-2": ("A", "Acquire BRICK if reasonably possible and build one road this turn."),
    "route-2": ("B", "Complete the assigned corridor if possible, then end your turn."),
    "transfer-3": ("C", "Acquire BRICK if reasonably possible and build one road this turn."),
    "update-2": ("D", "Acquire BRICK if reasonably possible and build one road this turn."),
    "route-1": ("E", "Complete the assigned corridor if possible, then end your turn."),
    "update-3": ("F", "Acquire BRICK if reasonably possible and build one road this turn."),
}
BRIEFINGS = {
    "game-1": ("Play your first full match. The club has attached a short trade observation from a separate "
               "practice game. Later positions may share counterparties but have independent hands."),
    "game-2": ("Play the second full match, with new seats and boards. The club assigned corridor B to "
               "practice table B (edge [5,16]) and corridor E to practice table E (edge [9,10]). "
               "These assignments apply when those practice tables open later."),
    "game-3": ("Play the third full match. The club attached a newer trade observation; use current evidence "
               "where relevant. After this full game, the league will open six practice tables."),
}
