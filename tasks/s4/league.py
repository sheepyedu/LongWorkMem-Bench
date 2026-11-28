"""Construct the fixed four-seat S4 board from its original action prefix."""

import json
from pathlib import Path


def create(name, cautious=False, strategic=True, track_wheat=True):
    from .arena import Arena

    if (name, cautious, strategic, track_wheat) != ("early-league", False, True, True):
        raise ValueError("Expected the fixed S4 board and opponent settings")
    exercise = json.loads(Path(__file__).with_name("board.json").read_text())
    arena = Arena(*exercise["game"])
    arena.advance()
    for action in exercise["prefix"]:
        arena.apply(**action)
    for player in arena.game.state.players:
        player.policy_version = exercise["version"]
        if player.name == "Ash":
            player.retain_last_brick = True
            player.protect_capital = True
        if player.name == "Flint":
            player.target_production = True
    arena.show_graph = exercise.get("graph", False)
    arena.track_wheat = track_wheat
    if arena.end_reason:
        raise RuntimeError("Completed exercise position")
    return arena
