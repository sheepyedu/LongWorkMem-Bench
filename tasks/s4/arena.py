"""Text projection and safe action adapter for the upstream Catan engine."""

from enum import Enum

from catanatron import Game
from catanatron.game import is_valid_action
from catanatron.models.board import STATIC_GRAPH
from catanatron.models.enums import (
    DEVELOPMENT_CARDS,
    RESOURCES,
    ActionPrompt,
)
from catanatron.models.enums import (
    ActionType as T,
)
from catanatron.models.player import Color
from catanatron.state_functions import (
    get_actual_victory_points,
    get_dev_cards_in_hand,
    get_player_freqdeck,
    get_visible_victory_points,
    player_has_rolled,
    player_num_dev_cards,
    player_num_resource_cards,
)

from .bots import NAMES, LeaguePlayer, trade_action


def wire(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [wire(x) for x in value]
    return value


def cards(counts):
    return {resource: count for resource, count in zip(RESOURCES, counts) if count}


def offer_deck(value):
    if not isinstance(value, dict) or not value or set(value) - set(RESOURCES):
        raise ValueError(
            "Use a nonempty resource object with WOOD, BRICK, SHEEP, WHEAT or ORE"
        )
    if any(type(x) is not int or x < 1 or x > 19 for x in value.values()):
        raise ValueError("Resource quantities must be positive integers")
    return [value.get(k, 0) for k in RESOURCES]


class Arena:
    show_graph = False
    track_wheat = False

    def __init__(self, seed, rotation=0, policy_version=1):
        colors = list(Color)
        seats = [
            LeaguePlayer(colors[(i + rotation) % 4], name, policy_version)
            for i, name in enumerate(NAMES)
        ]
        self.names = {player.color: player.name for player in seats}
        self.game = Game(seats, seed=seed)
        self.you = seats[0].color
        self.events = []
        self.actions = []
        self.offers_this_turn = {}
        self.actor_turns = 0
        self.end_reason = None

    def legal(self):
        return sorted(
            self.game.playable_actions,
            key=lambda a: (a.action_type.value, str(a.value)),
        )

    def event(self, record):
        action = record.action
        kind, value = action.action_type, action.value
        result = record.result
        if (
            kind in {T.DISCARD_RESOURCE, T.BUY_DEVELOPMENT_CARD}
            and action.color != self.you
        ):
            value, result = None, None
        if kind == T.MOVE_ROBBER and action.color != self.you and value[1] != self.you:
            result = None
        if kind in (T.OFFER_TRADE, T.ACCEPT_TRADE, T.REJECT_TRADE, T.CONFIRM_TRADE):
            value = {"give": cards(value[:5]), "take": cards(value[5:10])}
            if kind == T.CONFIRM_TRADE:
                value["partner"] = self.names[action.value[-1]]
        return {
            "seq": len(self.events) + 1,
            "round": self.game.state.num_turns,
            "player": self.names[action.color],
            "action": kind.value,
            "value": wire(value),
            "result": wire(result),
        }

    def execute(self, action):
        previous_turn = self.game.state.num_turns
        record = self.game.execute(action)
        event = self.event(record)
        if self.track_wheat:
            kind = action.action_type
            if kind == T.CONFIRM_TRADE:
                spent = (
                    event["value"]["give"].get("WHEAT")
                    if action.color == self.you
                    else event["value"]["take"].get("WHEAT")
                    if action.value[-1] == self.you
                    else False
                )
            else:
                spent = action.color == self.you and (
                    kind in {T.BUILD_SETTLEMENT, T.BUILD_CITY, T.BUY_DEVELOPMENT_CARD}
                    or kind == T.MARITIME_TRADE
                    and "WHEAT" in event["value"][:-1]
                )
            if spent:
                hand = get_player_freqdeck(self.game.state, self.you)
                event["wheat_after_spend"] = hand[RESOURCES.index("WHEAT")]
        self.events.append(event)
        if action.action_type == T.OFFER_TRADE:
            self.offers_this_turn[previous_turn] = (
                self.offers_this_turn.get(previous_turn, 0) + 1
            )
        if action.color == self.you and action.action_type == T.END_TURN:
            self.actor_turns += 1
        if self.game.winning_color():
            self.end_reason = "winner"
        elif self.game.state.num_turns >= 1000:
            self.end_reason = "engine_draw"

    def advance(self):
        while not self.end_reason:
            state = self.game.state
            if (
                state.current_prompt == ActionPrompt.DECIDE_TRADE
                and state.current_player_index == state.current_turn_index
            ):
                # This upstream revision can visit the proposer again when iterating seats.
                # Keep it out of player responses and drive the ordinary reject transition.
                self.game.execute(
                    next(a for a in self.legal() if a.action_type == T.REJECT_TRADE)
                )
                continue
            if state.current_color() == self.you:
                return
            player = state.current_player()
            self.execute(player.decide(self.game, self.legal()))

    def view(self, board=False, after=None):
        g, s = self.game, self.game.state
        view = {
            "position": len(self.events),
            "table_turn": s.num_turns,
            "completed_own_turns": self.actor_turns,
            "finished": self.end_reason,
            "phase": s.current_prompt.name,
            "order": [self.names[c] for c in s.colors],
            "turn_owner": self.names[s.colors[s.current_turn_index]],
            "players": [
                {
                    "player": self.names[c],
                    "color": c.value,
                    "public_vp": get_visible_victory_points(s, c),
                    "resource_count": player_num_resource_cards(s, c),
                    "development_count": player_num_dev_cards(s, c),
                }
                for c in s.colors
            ],
            "hand": cards(get_player_freqdeck(s, self.you)),
            "development_cards": {
                r: n
                for r in DEVELOPMENT_CARDS
                if (n := get_dev_cards_in_hand(s, self.you, r))
            },
            "buildings": {
                n: [self.names[c], t] for n, (c, t) in sorted(s.board.buildings.items())
            },
            "roads": [
                [*e, self.names[c]]
                for e, c in sorted(s.board.roads.items())
                if e[0] < e[1]
            ],
            "robber": wire(s.board.robber_coordinate),
            "offers_used_this_turn": self.offers_this_turn.get(s.num_turns, 0),
            "winner": self.names[g.winning_color()] if g.winning_color() else None,
        }
        if s.current_prompt in {
            ActionPrompt.DECIDE_TRADE,
            ActionPrompt.DECIDE_ACCEPTEES,
        }:
            view["current_offer"] = {
                "from": view["turn_owner"],
                "give": cards(s.current_trade[:5]),
                "take": cards(s.current_trade[5:10]),
            }
        if board:
            view["tiles"] = [
                [list(pos), tile.resource, tile.number, sorted(tile.nodes.values())]
                for pos, tile in sorted(s.board.map.land_tiles.items())
            ]
            view["ports"] = {
                k or "ANY": sorted(v) for k, v in s.board.map.port_nodes.items()
            }
            if self.show_graph:
                nodes = {
                    n
                    for tile in s.board.map.land_tiles.values()
                    for n in tile.nodes.values()
                }
                view["adjacency"] = {
                    n: sorted(
                        neighbor for neighbor in STATIC_GRAPH[n] if neighbor in nodes
                    )
                    for n in sorted(nodes)
                }
        if after is not None:
            view["events"] = self.events[after : after + 20]
            view["more_events"] = len(self.events) > after + 20
        return view

    def options(self):
        if self.end_reason or self.game.state.current_color() != self.you:
            return {"position": len(self.events), "actions": []}
        legal = []
        for i, action in enumerate(self.legal()):
            t, v = action.action_type, action.value
            if t in {T.ACCEPT_TRADE, T.REJECT_TRADE}:
                v = None
            elif t == T.CONFIRM_TRADE:
                v = self.names[v[-1]]
            elif t == T.MOVE_ROBBER:
                v = [v[0], self.names[v[1]] if v[1] else None]
            legal.append([i + 1, t.value, wire(v)])
        return {
            "position": len(self.events),
            "actions": legal,
            "can_offer": self.can_offer(),
        }

    def can_offer(self):
        s = self.game.state
        return (
            not self.end_reason
            and s.current_color() == self.you
            and s.current_prompt == ActionPrompt.PLAY_TURN
            and not s.is_road_building
            and player_has_rolled(s, self.you)
            and self.offers_this_turn.get(s.num_turns, 0) < 3
        )

    def apply(self, position, choice=None, give=None, take=None):
        if type(position) is not int or position != len(self.events):
            raise ValueError("Position changed; read legal actions again")
        if self.end_reason or self.game.state.current_color() != self.you:
            raise ValueError("No player action is pending")
        if choice is None:
            offered, asked = offer_deck(give), offer_deck(take)
            hand = get_player_freqdeck(self.game.state, self.you)
            action = trade_action(self.you, offered, asked)
            if (
                not self.can_offer()
                or any(q > h for q, h in zip(offered, hand))
                or not is_valid_action(
                    self.game.playable_actions, self.game.state, action
                )
            ):
                raise ValueError(
                    "Offer is not available here; check phase, available cards and trade limit"
                )
        else:
            legal = self.legal()
            if (
                type(choice) is not int
                or not 1 <= choice <= len(legal)
                or give is not None
                or take is not None
            ):
                raise ValueError("Choose an ID from the current actions list")
            action = legal[choice - 1]
        self.actions.append(
            {"position": position, "choice": choice, "give": give, "take": take}
        )
        start = len(self.events)
        self.execute(action)
        self.advance()
        return {
            "event": self.events[start],
            "responses": self.events[start + 1 : start + 13],
            "more_events": len(self.events) > start + 13,
            "state": self.view(),
            "legal": self.options(),
        }

    def score_state(self):
        return {
            "winner": self.view()["winner"],
            "end": self.end_reason,
            "vp": {
                name: get_actual_victory_points(self.game.state, c)
                for c, name in self.names.items()
            },
            "events": self.events,
            "actions": self.actions,
        }
