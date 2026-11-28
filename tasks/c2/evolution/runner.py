"""Native Claude Code entrypoint sharing the isolated calendar transport."""

from pathlib import Path
import sys
from tasks.c2 import pilot
from . import runner
from .scenario import setup, PROMPTS, VERSION, CHANNELS, release as issue
from .receiver import online, publish, archive

TOOLS = [
    {
        **s,
        "description": s["description"].replace(
            "查询频道的实际已收批次。",
            "查询在线批次；封存批次在 input/vault/index.json。",
        ),
        "inputSchema": {
            **s["inputSchema"],
            "properties": {
                k: ({**v, "description": "频道 A/B/C/D"} if k == "channel" else v)
                for k, v in s["inputSchema"]["properties"].items()
            },
        },
    }
    for s in pilot.TOOLS
]


def release(run, t):
    if t == 5:
        archive(run)
    return issue(run, t)


if __name__ == "__main__":
    if sys.argv[1] == "--serve":
        pilot.serve(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4], runner)
    else:
        pilot.run(Path(sys.argv[1]).resolve(), runner)
