"""Run paired staged C1 settlements with two OpenAI-compatible upstreams."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import getpass
import os
from pathlib import Path
from .pilot import run_session
from w1.gateway import MODEL, URL


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dest", type=Path)
    p.add_argument("--level", type=int, choices=(1, 2, 3), required=True)
    p.add_argument("--seeds", nargs="+", type=int, required=True)
    p.add_argument("--variants", nargs="+", choices=("A", "B"), default=["A", "B"])
    p.add_argument("--model", default=MODEL)
    p.add_argument("--url", default=URL)
    p.add_argument("--limit", type=int, default=180)
    p.add_argument(
        "--dispatch-after", type=int, choices=range(1, 51), metavar="COMMANDS"
    )
    p.add_argument("--rotate",action="store_true",help="Hand work files to fresh sessions in rounds 5 and 7")
    args = p.parse_args()
    if args.rotate and (args.level != 3 or not args.dispatch_after):
        p.error("Shift change requires the seven-round task and a dispatch window")
    if args.limit < 1 or len(set(args.seeds)) != len(args.seeds) or len(set(args.variants)) != len(args.variants):
        p.error("Use distinct seeds and variants and a positive request budget")
    key = os.getenv("C1_UPSTREAM_KEY") or getpass.getpass(
        "Upstream credential (hidden): "
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(
                run_session,
                args.dest / f"{seed}-{v}",
                v,
                "docker",
                key,
                mode="settlement",
                seed=seed,
                level=args.level,
                window=args.dispatch_after,
                rotate=args.rotate,
                limit=args.limit,
                model=args.model,
                url=args.url,
            )
            for seed in args.seeds
            for v in args.variants
        ]
        for f in futures:
            f.result()


if __name__ == "__main__":
    main()
