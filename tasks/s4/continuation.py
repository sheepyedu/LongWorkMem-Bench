"""Paired Catan continuation runs using one native Claude Code session per arm."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.w1.claude import run_claude
from tasks.w1.gateway import MODEL, URL, Gateway

from .engine import connect
from .grade import read_lines
from .pilot import write
from .public import CONTEXT
from .tools import ALLOWED, Table, broker

IMAGE = "longworkmem-catan:continuation"
PROTOCOL = "catan-continuation-v1"
FEEDER = [16, 21]
SPURS = {"west": ([6, 23], 6), "east": ([23, 52], 52)}
CASES = {"keep": "west", "revise": "east"}
ARMS = ("single", "switch")
OPPONENTS = ("base", "cautious")
PHASES = ("prepare", "revision", "interlude", "route", "delivery", "recovery")
STOP_ACTION = {
    "prepare": "BUILD_ROAD",
    "route": "BUILD_ROAD",
    "delivery": "BUILD_SETTLEMENT",
}


@dataclass(frozen=True)
class Episode:
    protocol: str
    phases: tuple[str, ...]
    prompt: Callable
    evaluate: Callable
    context: str
    cases: tuple[str, ...]
    arms: tuple[str, ...]
    opponents: tuple[str, ...]
    # Completed own turns permitted and events that close the segment early.
    rules: dict[str, tuple[int, tuple[str, ...]]] | None = None
    shared_turns: tuple[tuple[str, str], ...] = ()


GAME_CONTEXT = CONTEXT.split("A practice position")[0].replace(
    "Win each full match by playing it.", "Play the league work orders from the user."
) + (
    " A and B are separate desks; tool replies identify the active desk. A desk is paused "
    "when it is inactive. Material and work orders belong to their stated desk. "
    "A segment can pause inside an ordinary turn. Stop acting when segment_done is true. "
    "After an end of turn, other players can act until your next pending response."
)


def user_prompt(phase, arm, case):
    return {
        "prepare": (
            "Main desk A. The feeder is edge [16,21]. Build the feeder first; the segment pauses "
            "after your first road, before you need to end this ordinary turn. Keep at least two "
            "WHEAT in reserve when spending resources on A. The survey lists west as edge [6,23] "
            "ending at node 6, and east as edge [23,52] ending at node 52. West is authorized "
            "for the new spur and settlement unless a signed revision replaces it. "
            "The remaining work will resume later."
        ),
        "revision": (
            "Signed notice for A. The change request was withdrawn; the original survey authorization stands."
            if case == "keep"
            else "Signed notice for A. Replace the previously authorized spur and its endpoint with the east survey entry."
        )
        + " All other A orders stand. This is a read-only pause.",
        "interlude": (
            "Desk B needs an urgent separate job. Use its current turn to trade for one BRICK "
            "and spend it on any legal road there. You may spend B's WHEAT. End B's turn "
            "when done. A remains suspended and has no material transfers with B."
            if arm == "switch"
            else "The main desk is paused briefly. Check the live A position and report completed work. This is read-only."
        ),
        "route": (
            "Resume main desk A from its actual paused position. Build the currently authorized spur "
            "and preserve the active resource reservation. The desk pauses after your first road."
        ),
        "delivery": (
            "Continue the main desk A order. Deliver the authorized settlement. If more resources "
            "are needed, arrange a trade while respecting the active reservation. The first "
            "settlement or the end of the turn closes this segment."
        ),
        "recovery": (
            "Close the A work order. If the authorized settlement or feeder is still outstanding, "
            "use at most one additional ordinary turn to repair it, observing the active reserve. "
            "If the order is complete, verify the live board and report the outcome without further moves."
        ),
    }[phase]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Desk:
    def __init__(self, main, stack, trace, image, arm, rules=None, shared_turns=()):
        self.main, self.stack, self.trace, self.image, self.arm = (
            main,
            stack,
            trace,
            image,
            arm,
        )
        self.side = None
        self.rules = rules
        self.shared_turns = shared_turns
        self.phase = None
        self.seq = 0
        self.lock = threading.Lock()

    def start(self, phase):
        previous = self.phase
        self.phase = phase
        self.label = "B" if phase == "interlude" and self.arm == "switch" else "A"
        if self.label == "B":
            self.side = Table(
                self.stack.enter_context(connect(self.image)),
                self.trace / "engine-b.jsonl",
                self.main.note_file,
            )
            self.side.open("update-3")
        self.active = self.side if self.label == "B" else self.main
        if self.rules is None:
            self.active.set_goal(1)
            self.readonly = phase == "revision" or (
                phase == "interlude" and self.label == "A"
            )
            self.stop_actions = (STOP_ACTION.get(phase),)
        else:
            turns, self.stop_actions = self.rules[phase]
            if (previous, phase) not in self.shared_turns:
                self.active.set_goal(turns)
            self.readonly = turns == 0
        self.closed = self.readonly

    def snapshot(self, table=None):
        t = table or self.active
        return t.request("view", board=True), t.request("legal")

    def dispatch(self, name, args):
        with self.lock:
            if name == "act" and self.closed:
                result = {
                    "error": "This segment is paused or read-only",
                    "segment_done": True,
                }
            else:
                target = self.main if name == "notes" else self.active
                result = target.dispatch(name, args)
                event = result.get("event", {})
                if event and event.get("action") in self.stop_actions:
                    self.closed = True
                if name in {"look", "act"} and "state" in result:
                    result["segment_done"] = self.closed or self.active.done()
            result["desk"] = self.label
            self.seq += 1
            row = {
                "seq": self.seq,
                "table": self.label,
                "phase": self.phase,
                "tool": name,
                "args": args,
                "result": result,
            }
            with (self.trace / "mcp.jsonl").open("a") as stream:
                print(json.dumps(row, ensure_ascii=False), file=stream)
            return result


@contextmanager
def environment(image, trace, notes, arm, opponent, rules=None, shared_turns=()):
    with ExitStack() as stack:
        main = Table(
            stack.enter_context(connect(image)), trace / "engine-a.jsonl", notes
        )
        options = {"cautious": opponent == "cautious"}
        if opponent == "strategic":
            options["strategic"] = True
        if rules is not None:
            options["track_wheat"] = True
        main.open("continuation", **options)
        yield Desk(main, stack, trace, image, arm, rules, shared_turns)


def state_receipt(desk):
    return {
        "active": digest(desk.snapshot()),
        "main": digest(desk.snapshot(desk.main)),
        "position": desk.active.state["position"],
    }


def evaluate(case, rows):
    edge, node = SPURS[CASES[case]]
    a = [
        (r["phase"], r["result"]["event"], r["result"]["state"])
        for r in rows
        if r["table"] == "A" and r["tool"] == "act" and "event" in r["result"]
    ]
    prep = [e for p, e, _ in a if p == "prepare" and e["action"] == "BUILD_ROAD"]
    route = [e for p, e, _ in a if p == "route" and e["action"] == "BUILD_ROAD"]
    material = {
        "BUILD_ROAD",
        "BUILD_SETTLEMENT",
        "BUILD_CITY",
        "BUY_DEVELOPMENT_CARD",
        "CONFIRM_TRADE",
        "MARITIME_TRADE",
    }
    prep_material = [s for p, e, s in a if p == "prepare" and e["action"] in material]
    delivery_material = [
        s
        for p, e, s in a
        if p in {"route", "delivery", "recovery"} and e["action"] in material
    ]
    settle = next(
        (
            p
            for p, e, _ in a
            if p in {"delivery", "recovery"}
            and e["action"] == "BUILD_SETTLEMENT"
            and e["value"] == node
        ),
        None,
    )
    checks = {
        "feeder": [5 if prep and sorted(prep[0]["value"]) == FEEDER else 0, 5],
        "first_authorized_spur": [
            5 if route and sorted(route[0]["value"]) == edge else 0,
            5,
        ],
        "reserve_prepare": [
            2
            if prep_material
            and all(s["hand"].get("WHEAT", 0) >= 2 for s in prep_material)
            else 0,
            2,
        ],
        "reserve_resume": [
            3
            if delivery_material
            and all(s["hand"].get("WHEAT", 0) >= 2 for s in delivery_material)
            else 0,
            3,
        ],
        "authorized_settlement": [5 if settle else 0, 5],
    }
    b = [
        r["result"]["event"]
        for r in rows
        if r["table"] == "B" and r["tool"] == "act" and "event" in r["result"]
    ]
    bought_at = next(
        (
            e["seq"]
            for e in b
            if (
                e["action"] == "CONFIRM_TRADE"
                and e["value"]["take"].get("BRICK")
                or e["action"] == "MARITIME_TRADE"
                and e["value"][-1] == "BRICK"
            )
        ),
        None,
    )
    return {
        "score": sum(v[0] for v in checks.values()),
        "max": 20,
        "checks": checks,
        "first_spur": route[0]["value"] if route else None,
        "settlement_phase": settle,
        "side_delivery": bool(
            bought_at
            and any(e["seq"] > bought_at and e["action"] == "BUILD_ROAD" for e in b)
        ),
        "side_turn_ended": any(e["action"] == "END_TURN" for e in b),
    }


CONTINUATION = Episode(
    PROTOCOL, PHASES, user_prompt, evaluate, GAME_CONTEXT, tuple(CASES), ARMS, OPPONENTS
)


def run(dest, arm, case, opponent, key, upstream, image, *, episode=CONTINUATION):
    dest.mkdir(mode=0o700, parents=True)
    trace = dest / "trace"
    trace.mkdir()
    (trace / "mcp.jsonl").touch()
    session = str(uuid.uuid4())
    meta = {
        "protocol": episode.protocol,
        "arm": arm,
        "case": case,
        "opponent": opponent,
        "model": MODEL,
        "status": "running",
        "blocks": [],
        "start": datetime.now(UTC).isoformat(),
        "claude": subprocess.check_output(["claude", "--version"], text=True).strip(),
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "image": subprocess.check_output(
            ["docker", "image", "inspect", "-f", "{{.Id}}", image], text=True
        ).strip(),
    }
    write(dest / "manifest.json", meta)
    try:
        with (
            environment(
                meta["image"],
                trace,
                dest / "memory.json",
                arm,
                opponent,
                episode.rules,
                episode.shared_turns,
            ) as desk,
            broker(desk) as (address, token),
            Gateway(
                key,
                dest,
                allowed=ALLOWED,
                url=upstream,
                direct_response=True,
                timeout=135,
                private_markers=(
                    str(Path(__file__).resolve().parents[2]),
                    "score_state",
                ),
            ) as gw,
            TemporaryDirectory(prefix="s4-continuation-") as tmp,
        ):
            client = Path(tmp)
            (client / "desk").mkdir()
            config = {
                "mcpServers": {
                    "table": {
                        "command": sys.executable,
                        "args": ["-m", "tasks.s4.tools", address, token],
                        "env": {"PYTHONPATH": str(Path(__file__).resolve().parents[2])},
                    }
                }
            }
            for index, phase in enumerate(episode.phases, 1):
                desk.start(phase)
                before = state_receipt(desk)
                prompt = episode.prompt(phase, arm, case)
                (trace / f"prompt-{index}.txt").write_text(prompt)
                row = {
                    "index": index,
                    "phase": phase,
                    "table": desk.label,
                    "session": session,
                    "first_session": index == 1,
                    "first_tool": desk.seq + 1,
                    "first_request": gw.count + 1,
                    "start_position": before["position"],
                    "before": before,
                }
                meta["blocks"].append(row)
                write(dest / "manifest.json", meta)
                run_claude(
                    dest,
                    index,
                    gw,
                    session,
                    prompt,
                    client,
                    config=config,
                    context=episode.context,
                    allowed=ALLOWED,
                    first_session=index == 1,
                )
                after = state_receipt(desk)
                row.update(
                    last_tool=desk.seq,
                    last_request=gw.count,
                    end_position=after["position"],
                    after=after,
                )
                write(dest / "manifest.json", meta)
                print(
                    f"{arm}/{case} {phase} {before['position']} → {after['position']} ({gw.count} cumulative requests)",
                    flush=True,
                )
            meta["status"] = "complete"
    except BaseException as error:
        meta.update(status="error", error_type=type(error).__name__)
        raise
    finally:
        meta["end"] = datetime.now(UTC).isoformat()
        write(dest / "manifest.json", meta)


def replay(dest, image=None, *, episode=CONTINUATION):
    meta = json.loads((dest / "manifest.json").read_text())
    if meta["protocol"] != episode.protocol or meta["status"] != "complete":
        raise ValueError("Provide a complete run with the specified protocol")
    arm, case, opponent = meta["arm"], meta["case"], meta["opponent"]
    if (
        arm not in episode.arms
        or case not in episode.cases
        or opponent not in episode.opponents
    ):
        raise ValueError("Unknown continuation condition")
    blocks = meta["blocks"]
    if [row["phase"] for row in blocks] != list(episode.phases):
        raise ValueError("Continuation schedule mismatch")
    rows = list(read_lines(dest / "trace/mcp.jsonl"))
    with TemporaryDirectory() as tmp:
        trace = Path(tmp)
        with environment(
            image or meta["image"],
            trace,
            trace / "notes",
            arm,
            opponent,
            episode.rules,
            episode.shared_turns,
        ) as desk:
            states = {}
            for index, block in enumerate(blocks, 1):
                phase = block["phase"]
                desk.start(phase)
                if (
                    block["index"] != index
                    or block["table"] != desk.label
                    or state_receipt(desk) != block["before"]
                    or block["first_tool"] != desk.seq + 1
                    or not desk.seq <= block["last_tool"] <= len(rows)
                    or (dest / "trace" / f"prompt-{index}.txt").read_text()
                    != episode.prompt(phase, arm, case)
                ):
                    raise ValueError(f"Invalid phase boundary: {phase}")
                for row in rows[desk.seq : block["last_tool"]]:
                    got = desk.dispatch(row["tool"], row["args"])
                    if (
                        row["seq"] != desk.seq
                        or row["phase"] != phase
                        or row["table"] != desk.label
                        or got != row["result"]
                    ):
                        raise ValueError(
                            f"Transcript replay mismatch at tool {desk.seq}"
                        )
                if state_receipt(desk) != block["after"]:
                    raise ValueError(f"Invalid phase final state: {phase}")
                states[phase] = desk.active.state
            if desk.seq != len(rows):
                raise ValueError("Unconsumed tools")
    if episode.rules is None:
        return episode.evaluate(case, rows)
    return episode.evaluate(case, rows, states)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--arm", choices=ARMS, default="single")
    parser.add_argument("--case", choices=CASES, default="keep")
    parser.add_argument("--opponent", choices=OPPONENTS, default="cautious")
    parser.add_argument("--image")
    parser.add_argument("--upstream", default=URL)
    args = parser.parse_args()
    if not args.replay:
        key = os.getenv("ARK_API_KEY")
        if not key:
            parser.error("Set ARK_API_KEY or use the approved relay credential")
        run(
            args.dest,
            args.arm,
            args.case,
            args.opponent,
            key,
            args.upstream,
            args.image or IMAGE,
        )
    result = replay(args.dest, args.image)
    write(args.dest / "grade.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
