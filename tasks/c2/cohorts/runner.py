"""Single-session Claude Code entry for the customer migration edition."""

import sys
from pathlib import Path

from tasks.c2 import pilot
from tasks.c2.evolution.receiver import online
from tasks.c2.evolution.receiver import publish as dispatch
from tasks.c2.evolution.runner import TOOLS

from .scenario import (
    CHANNELS,
    MATERIAL_REVISION,
    PROMPTS,
    SCORING_REVISION,
    VERSION,
    setup,
)
from .scenario import (
    issue as release,
)

__all__ = [
    "TOOLS",
    "online",
    "CHANNELS",
    "VERSION",
    "MATERIAL_REVISION",
    "SCORING_REVISION",
    "PROMPTS",
    "setup",
    "release",
    "publish",
    "SERVER_MODULE",
]

SERVER_MODULE = "tasks.c2.cohorts.runner"


def publish(run, t, channel, key, file):
    if key.startswith("handover-") and (
        t < 8 or channel not in ("C", "D") or key != f"handover-{channel}-Q29"
    ):
        raise ValueError("recovery key not issued to this customer")
    return dispatch(run, t, channel, key, file)


if __name__ == "__main__":
    edition = sys.modules[__name__]
    if sys.argv[1] == "--serve":
        pilot.serve(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4], edition)
    else:
        pilot.run(Path(sys.argv[1]).resolve(), edition)
