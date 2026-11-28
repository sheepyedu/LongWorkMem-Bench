"""Fixed league schedule and engine-derived situation exercises."""

import json
from pathlib import Path

from .public import PRACTICE

GAMES = {"game-1": (17217, 0, 1), "game-2": (17219, 1, 1), "game-3": (17231, 2, 2)}
EXERCISES = json.loads(Path(__file__).with_name("fixtures.json").read_text())
SCHEDULE = [*GAMES, *PRACTICE]


def create(name, cautious=False, strategic=False, track_wheat=False):
    from .arena import Arena

    if name in GAMES:
        arena = Arena(*GAMES[name])
        arena.advance()
        return arena
    if name in ("continuation", "early-league"):
        exercise = json.loads(
            Path(__file__).with_name("continuation-board.json").read_text()
        )
    else:
        exercise = EXERCISES[name]
    arena = Arena(*exercise["game"])
    arena.advance()
    prefix = exercise["prefix"][:4] if name == "early-league" else exercise["prefix"]
    for action in prefix:
        arena.apply(**action)
    for player in arena.game.state.players:
        player.policy_version = exercise["version"]
        if (cautious or strategic) and player.name == "Ash":
            player.retain_last_brick = True
        if strategic and player.name == "Ash":
            player.protect_capital = True
        if strategic and player.name == "Flint":
            player.target_production = True
    arena.show_graph = exercise.get("graph", False)
    arena.track_wheat = track_wheat
    if arena.end_reason:
        raise RuntimeError("Completed exercise position")
    return arena
