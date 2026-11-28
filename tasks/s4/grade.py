"""Evaluator-only replay and score. Never copied into the game container."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from .engine import connect
from .league import GAMES, SCHEDULE
from .pilot import PROTOCOL
from .tools import Table

# The route targets come from earlier league assignments. Trade limits were
# frozen from engine-confirmed witness plays before model testing.
TARGET_EDGE = {"route-1": [9, 10], "route-2": [5, 16]}
TRADE_CAP = {"transfer-2": 1, "transfer-3": 1, "update-2": 2, "update-3": 2}


def evaluate_table(name, events, prefix, *, first_road=False):
    if name in GAMES:
        return {
            "victory_points": (min(events["vp"]["You"], 10) * 25 / 30, 25 / 3),
            "won": (5 if events["winner"] == "You" else 0, 5),
        }
    current = []
    for e in events["events"][prefix:]:
        if e["player"] == "You" and e["action"] == "END_TURN":
            break
        if e["player"] == "You":
            current.append(e)
    roads = [e for e in current if e["action"] == "BUILD_ROAD"]
    if name in TARGET_EDGE:
        return {
            "paved": (4 if roads else 0, 4),
            "assigned_edge": (
                6
                if any(
                    sorted(e["value"]) == TARGET_EDGE[name]
                    for e in (roads[:1] if first_road else roads)
                )
                else 0,
                6,
            ),
        }
    deals = []
    for e in current:
        if e["action"] == "CONFIRM_TRADE" and e["value"]["take"].get("BRICK"):
            deals.append((e["seq"], sum(e["value"]["give"].values())))
        if e["action"] == "MARITIME_TRADE" and e["value"][-1] == "BRICK":
            deals.append((e["seq"], sum(x is not None for x in e["value"][:-1])))
    first_offer = next(
        (e for e in current if e["action"] in ("MARITIME_TRADE", "OFFER_TRADE")), None
    )
    timely = any(deal[0] < road["seq"] for deal in deals for road in roads)
    # Charge the total cards paid for brick, including unnecessary extra purchases.
    efficient = bool(deals) and sum(cost for _, cost in deals) <= TRADE_CAP[name]
    first_paid = False
    if first_offer and deals:
        first_deal = deals[0][0]
        subsequent = [e for e in current if first_offer["seq"] < e["seq"] <= first_deal]
        first_paid = (
            first_offer["action"] == "MARITIME_TRADE"
            and first_deal == first_offer["seq"]
            or first_offer["action"] == "OFFER_TRADE"
            and not any(
                e["action"] in ("OFFER_TRADE", "MARITIME_TRADE", "CANCEL_TRADE")
                for e in subsequent
            )
        )
    return {
        "first_attempt": (3 if first_paid and efficient else 0, 3),
        "purchase_cost": (3 if efficient else 0, 3),
        "road_after_purchase": (4 if timely else 0, 4),
    }


def read_lines(path):
    with path.open() as stream:
        for no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Unreadable {path.name} line {no}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"Expected an object in {path.name} line {no}")
                yield row


def replay(run, image=None, local=False, *, first_road=False):
    manifest = json.loads((run / "manifest.json").read_text())
    if (
        manifest["protocol"] != PROTOCOL
        or manifest["status"] != "complete"
        or manifest["schedule"] != SCHEDULE
    ):
        raise ValueError("A complete S4 run with the frozen schedule is required")
    blocks = manifest["blocks"]
    sessions = {
        name: {b["session"] for b in blocks if b["table"] == name} for name in SCHEDULE
    }
    if any(len(ids) != 1 for ids in sessions.values()) or len(
        set.union(*(sessions[n] for n in GAMES))
    ) != len(GAMES):
        raise ValueError("Wrong S4 session schedule")
    if any(sessions[n] != sessions["game-3"] for n in SCHEDULE if n not in GAMES):
        raise ValueError("Practice tables must use the third session")
    if [r["index"] for r in blocks] != list(range(1, len(blocks) + 1)):
        raise ValueError("Noncontiguous block IDs")
    if list(dict.fromkeys(b["table"] for b in blocks)) != SCHEDULE:
        raise ValueError("Unexpected table sequence")
    journal = list(read_lines(run / "trace/mcp.jsonl"))
    if [m["seq"] for m in journal] != list(range(1, len(journal) + 1)):
        raise ValueError("Noncontiguous tool journal")
    groups = defaultdict(list)
    for b in blocks:
        groups[b["table"]].append(b)
    checks = []
    summaries = {}
    use = 0
    with (
        TemporaryDirectory() as tmp,
        connect(image or manifest["image"], local=local) as eng,
    ):
        table = Table(eng, Path(tmp) / "tools.jsonl", Path(tmp) / "notes.json")
        for name in SCHEDULE:
            init = table.open(name)
            prefix = init["position"]
            if prefix != manifest["tables"][name]["initial_position"]:
                raise ValueError(f"{name}: starting snapshot mismatch")
            for block in groups[name]:
                if (
                    use + 1 != block["first_tool"]
                    or block["start_position"] != table.state["position"]
                ):
                    raise ValueError(f"{name}: block boundary mismatch")
                max_own_turns = 7 if name in GAMES else 1
                if (
                    block["target"]
                    != table.state["completed_own_turns"] + max_own_turns
                ):
                    raise ValueError(f"{name}: unexpected segment target")
                table.goal = block["target"]
                while use < block["last_tool"]:
                    m = journal[use]
                    if (
                        m["table"] != name
                        or table.dispatch(m["tool"], m["args"]) != m["result"]
                    ):
                        raise ValueError(f"{name}: tool replay mismatch at {use + 1}")
                    use += 1
                if (
                    table.state["position"] != block["end_position"]
                    or table.done() != block["segment_done"]
                ):
                    raise ValueError(f"{name}: frozen block output mismatch")
            events = table.request("end_state")
            archived = json.loads((run / "trace" / f"{name}-events.json").read_text())
            if events != archived:
                raise ValueError(f"{name}: terminal state differs from replay")
            summaries[name] = {
                "winner": events["winner"],
                "vp": events["vp"],
                "end": events["end"],
                "stall": manifest["tables"][name].get("stall", False),
                "player_actions": len(events["actions"]) - len(create_prefix(name)),
                "events": len(events["events"]) - prefix,
            }
            for check, (points, maximum) in evaluate_table(
                name, events, prefix, first_road=first_road
            ).items():
                checks.append(
                    {"table": name, "check": check, "earned": points, "max": maximum}
                )
    if use != len(journal):
        raise ValueError("Unconsumed tool journal")
    return {
        "score": round(sum(r["earned"] for r in checks), 4),
        "max": 100,
        "scorer": "catan-v1.1" if first_road else "catan-v1",
        "checks": checks,
        "tables": summaries,
        "replay_image": None if local else image or manifest["image"],
    }


def create_prefix(name):
    from .league import EXERCISES

    return EXERCISES.get(name, {}).get("prefix", [])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--image")
    p.add_argument(
        "--local",
        action="store_true",
        help="Replay with the pinned dependencies installed locally",
    )
    p.add_argument(
        "--first-road",
        action="store_true",
        help="Re-score the prior corridor on the first paved edge only",
    )
    args = p.parse_args()
    try:
        result = replay(args.run, args.image, args.local, first_road=args.first_road)
    except (KeyError, IndexError, TypeError, ValueError, OSError, RuntimeError) as exc:
        print(
            json.dumps(
                {"valid": False, "score": None, "error": str(exc)}, ensure_ascii=False
            )
        )
        raise SystemExit(2) from None
    with (args.run / ("checks-v1.1.csv" if args.first_road else "checks.csv")).open(
        "w", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=("table", "check", "earned", "max"))
        writer.writeheader()
        writer.writerows(result["checks"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
