"""Fixed league schedule and engine-derived situation exercises."""

import json
from pathlib import Path

from .public import PRACTICE

GAMES = {"game-1": (17217, 0, 1), "game-2": (17219, 1, 1), "game-3": (17231, 2, 2)}
EXERCISES = json.loads(Path(__file__).with_name("fixtures.json").read_text())
SCHEDULE = [*GAMES, *PRACTICE]


def create(name):
    from .arena import Arena

    if name in GAMES:
        arena = Arena(*GAMES[name])
        arena.advance()
        return arena
    exercise = EXERCISES[name]
    arena = Arena(*exercise["game"])
    arena.advance()
    for action in exercise["prefix"]:
        arena.apply(**action)
    for player in arena.game.state.players:
        player.policy_version = exercise["version"]
    if arena.end_reason:
        raise RuntimeError("Completed exercise position")
    return arena
