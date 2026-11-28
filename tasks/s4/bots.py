"""Benchmark opponents. All strategy uses the acting seat's observation."""

from catanatron.models.board import STATIC_GRAPH
from catanatron.models.enums import RESOURCES, Action
from catanatron.models.enums import ActionType as T
from catanatron.models.player import Player
from catanatron.state_functions import get_player_freqdeck, get_visible_victory_points

NAMES = ("You", "Ash", "Flint", "Sail")
WEIGHT = {
    "You": (3, 3, 2, 3, 3),
    "Ash": (3, 5, 2, 3, 2),
    "Flint": (2, 2, 2, 4, 5),
    "Sail": (2, 3, 4, 3, 3),
}


def trade_action(color, give, take):
    return Action(color, T.OFFER_TRADE, tuple(give + take))


class LeaguePlayer(Player):
    def __init__(self, color, name, policy_version=1):
        super().__init__(color)
        self.name = name
        self.policy_version = policy_version

    def accepts(self, offered, requested, hand, proposer_points):
        weights = WEIGHT[self.name]
        offered_value = sum(q * w for q, w in zip(offered, weights))
        requested_value = sum(q * w for q, w in zip(requested, weights))
        if (
            self.name == "Ash"
            and requested[1]
            and hand[1] >= requested[1] + 1
            and self.policy_version == 1
        ):
            requested_value = min(
                requested_value, 2 * requested[1] + sum(requested) - requested[1]
            )
        if self.name == "Flint" and requested[2] and hand[2] >= requested[2] + 1:
            requested_value -= requested[2]
        lead_tax = 2 if self.name == "Sail" and proposer_points >= 6 else 0
        return offered_value >= requested_value + lead_tax and all(
            not q or h >= q for q, h in zip(requested, hand)
        )

    def decide(self, game, playable_actions):
        state = game.state
        hand = get_player_freqdeck(state, self.color)
        options = sorted(
            playable_actions, key=lambda a: (a.action_type.value, str(a.value))
        )
        first = options[0]
        if first.action_type in {T.ACCEPT_TRADE, T.REJECT_TRADE}:
            proposer = state.colors[state.current_turn_index]
            offered, requested = first.value[:5], first.value[5:10]
            accept = self.accepts(
                offered, requested, hand, get_visible_victory_points(state, proposer)
            )
            return next(
                (a for a in options if a.action_type == T.ACCEPT_TRADE and accept),
                options[-1],
            )
        if any(a.action_type == T.CANCEL_TRADE for a in options):
            return next((a for a in options if a.action_type == T.CONFIRM_TRADE), first)

        board = state.board

        def production(node):
            tiles = board.map.adjacent_tiles.get(node, [])
            return sum(
                (6 - abs(7 - t.number)) * WEIGHT[self.name][RESOURCES.index(t.resource)]
                for t in tiles
                if t.number and t.resource
            )

        def rate(action):
            kind, value = action.action_type, action.value
            if kind == T.BUILD_SETTLEMENT:
                return 160 + production(value)
            if kind == T.BUILD_CITY:
                return 210 + production(value)
            if kind == T.BUILD_ROAD:
                targets = [n for n in value if n not in board.buildings]
                if not targets:
                    return -20

                def open_node(n):
                    return n not in board.buildings and all(
                        x not in board.buildings for x in STATIC_GRAPH[n]
                    )

                return max(
                    (
                        75 + production(n)
                        if open_node(n)
                        else 20
                        + max(
                            (production(x) for x in STATIC_GRAPH[n] if open_node(x)),
                            default=0,
                        )
                        for n in targets
                    ),
                    default=-20,
                )
            if kind == T.ROLL:
                return 130
            if kind == T.BUY_DEVELOPMENT_CARD:
                return 62
            if kind in (
                T.PLAY_KNIGHT_CARD,
                T.PLAY_YEAR_OF_PLENTY,
                T.PLAY_ROAD_BUILDING,
                T.PLAY_MONOPOLY,
            ):
                return 100
            if kind == T.DISCARD_RESOURCE:
                return (
                    10 * hand[RESOURCES.index(value)]
                    - WEIGHT[self.name][RESOURCES.index(value)]
                )
            if kind == T.MOVE_ROBBER:
                tile, victim = value
                nodes = board.map.land_tiles[tile].nodes.values()
                return (
                    get_visible_victory_points(state, victim) * 3 if victim else 0
                ) - 25 * any(
                    board.buildings.get(n, (None,))[0] == self.color for n in nodes
                )
            if kind == T.MARITIME_TRADE:
                return (
                    18
                    if hand[RESOURCES.index(value[0])] >= 5
                    and hand[RESOURCES.index(value[-1])] == 0
                    else -10
                )
            if kind == T.END_TURN:
                return 0
            return -30

        best = max(options, key=rate)
        if (
            best.action_type == T.END_TURN
            and self.name != "You"
            and self.last_offer != state.num_turns
        ):
            give = max(range(5), key=lambda k: (hand[k], -WEIGHT[self.name][k]))
            take = max(range(5), key=lambda k: (hand[k] == 0, WEIGHT[self.name][k]))
            if hand[give] >= 3 and not hand[take]:
                offer, ask = [0] * 5, [0] * 5
                offer[give] = ask[take] = 1
                self.last_offer = state.num_turns
                return trade_action(self.color, offer, ask)
        return best

    last_offer = -1
