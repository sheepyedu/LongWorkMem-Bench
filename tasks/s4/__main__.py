"""Run S4 or regrade its existing trajectory offline."""

import argparse
import json
import os
from pathlib import Path

from tasks.w1.gateway import URL

from .codex import run_codex_game
from .engine import IMAGE
from .records import write
from .runtime import replay, run_claude_game


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--harness", choices=("claude", "codex"), default="claude")
    parser.add_argument("--model", default="gpt-6.1-terra", help="Codex model")
    parser.add_argument("--effort", default="low", help="Codex reasoning effort")
    parser.add_argument("--upstream", default=URL, help="Claude gateway upstream")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if not args.replay:
        if args.harness == "codex":
            run_codex_game(args.run, args.image, args.model, args.effort)
        else:
            key = os.getenv("ARK_API_KEY")
            if not key:
                parser.error("Set ARK_API_KEY for a live Claude run")
            run_claude_game(args.run, key, args.upstream, args.image)
    result = replay(args.run, args.image)
    write(args.run / "grade.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
