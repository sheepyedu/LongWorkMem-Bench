"""Single-board S4 task runtime and deterministic engine replay."""

import hashlib
import json
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.w1.claude import run_claude
from tasks.w1.gateway import MODEL, Gateway

from .engine import connect
from .records import read_lines, write
from .schedule import CONTEXT, PHASES, PROMPTS, PROTOCOL, RULES, SHARED_TURNS
from .scoring import grade, player_trade
from .tools import ALLOWED, Table, broker


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Desk:
    label = "A"

    def __init__(self, table, trace):
        self.active = table
        self.trace = trace
        self.phase = None
        self.seq = 0
        self.lock = threading.Lock()

    def start(self, phase):
        previous = self.phase
        self.phase = phase
        turns, self.stop_actions = RULES[phase]
        if (previous, phase) not in SHARED_TURNS:
            self.active.set_goal(turns)
        self.closed = turns == 0

    def snapshot(self):
        t = self.active
        return t.request("view", board=True), t.request("legal")

    def dispatch(self, name, args):
        with self.lock:
            if name == "act" and self.closed:
                result = {
                    "error": "This segment is paused or read-only",
                    "segment_done": True,
                }
            else:
                result = self.active.dispatch(name, args)
                event = result.get("event", {})
                if event and event.get("action") in self.stop_actions:
                    self.closed = True
                if event and self.phase == "clearing" and not self.closed:
                    # A bot can settle a trade with our seat while the engine advances.
                    replies = result["responses"]
                    after = replies[-1]["seq"] if replies else event["seq"]
                    while result["state"]["position"] > after:
                        page = self.active.request("view", after=after)["events"]
                        if not page:
                            raise ValueError("Incomplete engine trade receipt")
                        replies = [*replies, *page]
                        after = page[-1]["seq"]
                    self.closed = any(player_trade(e) is not None for e in replies)
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
def environment(image, trace, notes):
    with connect(image) as engine:
        table = Table(engine, trace / "engine-a.jsonl", notes)
        table.open("early-league", cautious=False, strategic=True, track_wheat=True)
        yield Desk(table, trace)


def state_receipt(desk):
    fingerprint = digest(desk.snapshot())
    return {
        "active": fingerprint,
        "main": fingerprint,
        "position": desk.active.state["position"],
    }


def run_claude_game(dest, key, upstream, image):
    dest.mkdir(mode=0o700, parents=True)
    trace = dest / "trace"
    trace.mkdir()
    (trace / "mcp.jsonl").touch()
    session = str(uuid.uuid4())
    meta = {
        "protocol": PROTOCOL,
        "arm": "single",
        "case": "site21",
        "opponent": "strategic",
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
            environment(meta["image"], trace, dest / "memory.json") as desk,
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
            TemporaryDirectory(prefix="s4-") as tmp,
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
            for index, phase in enumerate(PHASES, 1):
                desk.start(phase)
                before = state_receipt(desk)
                prompt = PROMPTS[phase]
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
                    context=CONTEXT,
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
                    f"{phase} {before['position']} → {after['position']} ({gw.count} cumulative requests)",
                    flush=True,
                )
                if desk.active.state["finished"]:
                    break
            meta["status"] = "complete"
    except BaseException as error:
        meta.update(status="error", error_type=type(error).__name__)
        raise
    finally:
        meta["end"] = datetime.now(UTC).isoformat()
        write(dest / "manifest.json", meta)


def replay(dest, image=None):
    meta = json.loads((dest / "manifest.json").read_text())
    if (
        meta["protocol"],
        meta["status"],
        meta["arm"],
        meta["case"],
        meta["opponent"],
    ) != (PROTOCOL, "complete", "single", "site21", "strategic"):
        raise ValueError(
            "Expected a completed S4 40-turn run with the fixed board and seats"
        )
    blocks = meta["blocks"]
    expected = PHASES[: len(blocks)]
    if not blocks or [row["phase"] for row in blocks] != list(expected):
        raise ValueError("S4 schedule mismatch")
    rows = list(read_lines(dest / "trace/mcp.jsonl"))
    with TemporaryDirectory() as tmp:
        trace = Path(tmp)
        with environment(image or meta["image"], trace, trace / "notes") as desk:
            states = {}
            for index, block in enumerate(blocks, 1):
                phase = block["phase"]
                desk.start(phase)
                if (
                    any(
                        type(block[k]) is not int
                        for k in ("index", "first_tool", "last_tool")
                    )
                    or block["index"] != index
                    or block["table"] != desk.label
                    or state_receipt(desk) != block["before"]
                    or block["first_tool"] != desk.seq + 1
                    or not desk.seq <= block["last_tool"] <= len(rows)
                    or (dest / "trace" / f"prompt-{index}.txt").read_text()
                    != PROMPTS[phase]
                ):
                    raise ValueError(f"Invalid phase boundary: {phase}")
                for row in rows[desk.seq : block["last_tool"]]:
                    got = desk.dispatch(row["tool"], row["args"])
                    if (
                        type(row["seq"]) is not int
                        or row["seq"] != desk.seq
                        or row["phase"] != phase
                        or row["table"] != desk.label
                        or digest(got) != digest(row["result"])
                    ):
                        raise ValueError(
                            f"Transcript replay mismatch at tool {desk.seq}"
                        )
                if state_receipt(desk) != block["after"]:
                    raise ValueError(f"Invalid phase final state: {phase}")
                states[phase] = desk.active.state
                if desk.active.state["finished"] and index != len(blocks):
                    raise ValueError("Unexpected work after game terminal")
            if len(blocks) < len(PHASES) and not desk.active.state["finished"]:
                raise ValueError("Short schedule without engine terminal")
            if desk.seq != len(rows):
                raise ValueError("Unconsumed tools")
            history = desk.active.request("end_state")["events"]
            if any(e["seq"] != n for n, e in enumerate(history, 1)):
                raise ValueError("Incomplete engine history")
            events = {
                b["phase"]: history[b["before"]["position"] : b["after"]["position"]]
                for b in blocks
            }
    return grade(rows, states, events)
