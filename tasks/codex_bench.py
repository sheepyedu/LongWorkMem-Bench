"""Run a fixed public LongWorkMem task using native Codex threads and Docker."""

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .codex_client import Client, MODEL
from .protocol import PROTOCOL, PUBLIC_SEED, PUBLIC_VARIANT
from .c1 import pilot, sandbox, settlement_grade
from .c1.runstate import freeze as freeze_desk
from .s1.circuit import Circuit, read_command
from .s1.engine import exchange, open_engine
from .w1 import advanced, office
from .w1.pilot import CONTEXT, docker_image, isolation_check
from .w1.runstate import freeze, prepare


def specs_for(task):
    if task == "s1":
        return []
    prefix, tools = (
        ("office", office.TOOLS) if task == "w1" else ("workshop", [sandbox.TOOL])
    )
    return [{**s, "name": prefix + "_" + s["name"]} for s in tools]


def recorded_turn(run, idx, thread, prompt, allowed):
    """Match native turn IDs, the user input, tool round trips and the final answer."""
    path = run / "trace" / f"turn-{idx}.jsonl"
    calls, dispatches = {}, {}
    final = None
    start_id = turn_id = None
    completed = False
    for line in path.read_text().splitlines():
        row = json.loads(line)
        direction, msg = row["direction"], row["message"]
        params = msg.get("params", {})
        method = msg.get("method")
        if method == "turn/start":
            if (
                start_id is not None
                or direction != "send"
                or params["threadId"] != thread
            ):
                raise ValueError("Codex turn start differs")
            if (
                params["input"] != [dict(type="text", text=prompt)]
                or params["environments"] != []
            ):
                raise ValueError("Codex turn input or environment differs")
            start_id = msg["id"]
        elif (
            method is None
            and direction == "recv"
            and msg.get("id") == start_id
            and "result" in msg
        ):
            turn_id = msg["result"]["turn"]["id"]
        elif method in ("item/completed", "item/tool/call", "turn/completed"):
            event_turn = (
                params["turn"]["id"] if method == "turn/completed" else params["turnId"]
            )
            if (
                not turn_id
                or event_turn != turn_id
                or params["threadId"] != thread
                or completed
            ):
                raise ValueError("Codex event from wrong turn or session")
            if method == "item/tool/call":
                if (
                    params["tool"] not in allowed
                    or msg["id"] in dispatches
                    or params["callId"] in calls
                ):
                    raise ValueError("Unexpected Codex tool")
                dispatches[msg["id"]] = params["callId"]
                calls[params["callId"]] = dict(
                    tool=params["tool"], arguments=params["arguments"]
                )
            elif method == "turn/completed":
                completed = params["turn"]["status"] == "completed"
            else:
                item = params["item"]
                if item["type"] == "agentMessage":
                    final = item["text"]
                elif item["type"] == "dynamicToolCall":
                    call = calls.get(item["id"], {})
                    if any(
                        call.get(k) != item[k]
                        for k in ("tool", "arguments", "success", "contentItems")
                    ):
                        raise ValueError(
                            "Codex tool request or result differs from native completion"
                        )
                    if call.get("done"):
                        raise ValueError("Duplicate tool completion")
                    call["done"] = True
                elif item["type"] not in (
                    "userMessage",
                    "reasoning",
                    "contextCompaction",
                    "plan",
                ):
                    raise ValueError("Unexpected native action " + item["type"])
        elif direction == "send" and "result" in msg:
            if msg["id"] not in dispatches:
                raise ValueError("Unmatched Codex tool response")
            calls[dispatches.pop(msg["id"])].update(msg["result"])
    if (
        not completed
        or final is None
        or dispatches
        or not all(c.get("done") for c in calls.values())
    ):
        raise ValueError("Incomplete native Codex turn")
    return final


def native_usage(run, meta):
    """Totals are cumulative per thread. Keep its last observation across user turns."""
    sessions = {}
    updates = 0
    tools = 0
    compact = 0
    missing = []
    for entry in meta["turns"]:
        for idx in entry["attempts"]:
            observed = False
            for line in (run / "trace" / f"turn-{idx}.jsonl").read_text().splitlines():
                msg = json.loads(line)["message"]
                method = msg.get("method")
                if method == "thread/tokenUsage/updated":
                    params = msg["params"]
                    sessions[params["threadId"]] = params["tokenUsage"]["total"]
                    updates += 1
                    observed = True
                elif method == "item/tool/call":
                    tools += 1
                elif (
                    method == "item/completed"
                    and msg["params"]["item"]["type"] == "contextCompaction"
                ):
                    compact += 1
            if not observed:
                missing.append(idx)
    result = dict(
        usage_updates=updates,
        tool_calls=tools,
        compact_events=compact,
        missing_usage_attempts=missing,
    )
    if sessions and not missing:
        for field in (
            "inputTokens",
            "outputTokens",
            "cachedInputTokens",
            "reasoningOutputTokens",
            "totalTokens",
        ):
            result[field] = sum(v[field] for v in sessions.values())
    return result


def verify_threads(run, meta, task, shifts):
    threads = [
        json.loads(line)
        for line in (run / "trace/threads.jsonl").read_text().splitlines()
    ]
    allowed = [s["name"] for s in specs_for(task)]
    if len(threads) != len(shifts) or len({x["thread"] for x in threads}) != len(
        shifts
    ):
        raise ValueError("Wrong number of Codex sessions")
    if any(
        x["model"] != meta["model"]
        or x["tools"] != allowed
        or x["effort"] != meta["effort"]
        for x in threads
    ):
        raise ValueError("Unexpected model, tools or reasoning setting")
    return dict(zip(shifts, (x["thread"] for x in threads))), allowed


def replay(run):
    meta = json.loads((run / "manifest.json").read_text())
    task = meta["task_id"]
    expected = dict(
        harness="codex-app-server",
        seed=PUBLIC_SEED,
        variant=PUBLIC_VARIANT,
        protocol=PROTOCOL,
        status="complete",
        backend="docker",
        limit=None,
    )
    if any(k not in meta or meta[k] != v for k, v in expected.items()):
        raise ValueError("Manifest differs from the completed public Codex protocol")
    shifts = {"w1": [1], "c1": [1, 5, 7], "s1": [1, 41]}[task]
    threads, allowed = verify_threads(run, meta, task, shifts)
    count = {"w1": 9, "c1": 7, "s1": 80}[task]
    if [x["turn"] for x in meta["turns"]] != list(range(1, count + 1)):
        raise ValueError("Incomplete schedule")
    submitted = {
        f"turn-{idx}.jsonl" for row in meta["turns"] for idx in row["attempts"]
    }
    files = {path.name for path in (run / "trace").glob("turn-*.jsonl")}
    if files != submitted:
        raise ValueError("Unaccounted or missing Codex attempt")
    circuit = (
        Circuit(PUBLIC_SEED, PUBLIC_VARIANT, 10, 2, 2, version=3)
        if task == "s1"
        else None
    )
    # Fixed public prompt scripts are regenerated without model work products.
    prompts = {}
    if not circuit:
        with TemporaryDirectory() as tmp:
            for t in range(1, count + 1):
                if task == "c1":
                    prompts[t] = pilot.release_turn(
                        Path(tmp), t, PUBLIC_VARIANT, PUBLIC_SEED, 3, None, True
                    )
                    snapshot = run / "snapshots" / str(t)
                    if advanced.public_digest(
                        snapshot, prompts[t]
                    ) != advanced.public_digest(Path(tmp), prompts[t]):
                        raise ValueError(
                            f"C1 public input snapshot differs at turn {t}"
                        )
                else:
                    prompts[t] = advanced.release(
                        Path(tmp), t, PUBLIC_VARIANT, 8, PUBLIC_SEED, erp_window=False
                    )
                    if (
                        advanced.public_digest(Path(tmp), prompts[t])
                        != meta["turns"][t - 1]["public_digest"]
                    ):
                        raise ValueError(f"W1 public materials differ at turn {t}")
    receipts = []
    memo = ""
    for t, entry in enumerate(meta["turns"], 1):
        session = threads[max(k for k in shifts if k <= t)]
        prompt = (run / "trace" / f"prompt-{t}.txt").read_text()
        if entry["session"] != session:
            raise ValueError("Incorrect handover")
        if prompt != (circuit.prompt(t, "handover", memo) if circuit else prompts[t]):
            raise ValueError("Incorrect public prompt or handover memo")
        attempts = entry["attempts"]
        if attempts != [t] and not (circuit and attempts == [t, t + count]):
            raise ValueError("Unexpected attempts")
        for idx in attempts:
            answer = recorded_turn(run, idx, session, prompt, allowed)
            if circuit:
                try:
                    receipt = circuit.submission(t, read_command(answer, 4), "handover")
                except ValueError as exc:
                    if len(attempts) == 1:
                        raise ValueError("Missing format retry") from exc
                    prompt = f"单据格式未接收：{exc}。请重交本轮单据。"
                    receipt = circuit.receipt(t, {}, "handover")
                else:
                    if idx != attempts[-1]:
                        raise ValueError("Valid answer retried")
        if circuit:
            if receipt != json.loads((run / f"receipt-{t}.json").read_text()):
                raise ValueError("S1 receipt mismatch")
            memo = receipt.get("memo", memo)
            receipts.append(receipt)
    if circuit:
        result = circuit.score(receipts)
    elif task == "w1":
        result = advanced.grade(run, details=True)
    else:
        result = settlement_grade.grade(run, "docker")
    result["usage"] = native_usage(run, meta)
    return result


def run_task(task, run, model, effort):
    seed, v = PUBLIC_SEED, PUBLIC_VARIANT
    if task == "w1":
        work = prepare(run)
    else:
        run.mkdir(parents=True, mode=0o700, exist_ok=False)
        (run / "trace").mkdir()
        work = run / "work"
        if task == "c1":
            for name in ("input", *sandbox.WRITABLE):
                (work / name).mkdir(parents=True)

    def save(obj):
        pilot.write_json(run / "manifest.json", obj)

    meta = dict(
        task_id=task,
        harness="codex-app-server",
        model=model,
        effort=effort,
        seed=seed,
        variant=v,
        protocol=PROTOCOL,
        condition="public",
        backend="docker",
        limit=None,
        status="running",
        turns=[],
        start=pilot.timestamp(),
        codex=subprocess.check_output(["codex", "--version"], text=True).strip(),
        git=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True
        ).strip(),
    )
    save(meta)
    try:
        engine_context = nullcontext((None, None))
        if task == "w1":
            meta.update(
                task="W1-advanced",
                level=8,
                erp_window=False,
                docker_image=docker_image(),
                isolation=isolation_check(work, "docker"),
            )
            context = (
                CONTEXT + "本办公室支持使用 soffice --headless 在副本上实际重算 Excel。"
            )
            turns, shifts = 9, (1,)
        elif task == "c1":
            meta.update(
                mode="settlement",
                level=3,
                image=sandbox.image_id(),
                rotation_turns=[5, 7],
                withdraw_handover=True,
                dispatch_window=None,
                isolation=pilot.check_boundary(work, "docker"),
            )
            context = pilot.CONTEXT
            turns, shifts = 7, (1, 5, 7)
        else:
            engine_context = open_engine(seed, v, 10, 2, 2)
            meta.update(
                level=2,
                desks=10,
                qualifiers=2,
                score_version=3,
                parser_version=4,
                history="handover",
            )
            context = Circuit(seed, v, 10, 2, 2, version=3).rules
            turns, shifts = 80, (1, 41)
        with engine_context as (engine, image), Client(run, model, effort) as client:
            if image:
                meta["engine_image"] = image
            memo = ""
            for t in range(1, turns + 1):
                if t in shifts:
                    client.start(context, specs_for(task))
                entry = dict(turn=t, session=client.thread, attempts=[t])
                if task == "w1":
                    prompt = advanced.release(work, t, v, 8, seed, erp_window=False)
                    entry["public_digest"] = advanced.public_digest(work, prompt)
                elif task == "c1":
                    prompt = pilot.release_turn(work, t, v, seed, 3, None, True)
                else:
                    prompt = exchange(engine, "prompt", t, "handover", memo)
                (run / "trace" / f"prompt-{t}.txt").write_text(prompt)

                def tool(name, args):
                    if name == "workshop_shell":
                        return sandbox.shell(
                            work, args["command"], "docker", image=meta["image"]
                        )
                    if name == "office_shell":
                        return office.shell(
                            work, args["command"], "docker", image=meta["docker_image"]
                        )
                    return {
                        "receipt": office.act(
                            run, t, name.removeprefix("office_"), **args
                        )
                    }

                answer, usage = client.turn(t, prompt, tool if task != "s1" else None)
                if task == "w1":
                    freeze(run, t)
                elif task == "c1":
                    entry["omissions"] = freeze_desk(work, run / "snapshots" / str(t))
                else:
                    try:
                        receipt = exchange(
                            engine, "submit", t, read_command(answer, 4), "handover"
                        )
                    except ValueError as exc:
                        idx = t + turns
                        entry["attempts"].append(idx)
                        answer, usage = client.turn(
                            idx, f"单据格式未接收：{exc}。请重交本轮单据。"
                        )
                        try:
                            receipt = exchange(
                                engine, "submit", t, read_command(answer, 4), "handover"
                            )
                        except ValueError:
                            receipt = exchange(engine, "empty", t, "handover")
                    pilot.write_json(run / f"receipt-{t}.json", receipt)
                    memo = receipt.get("memo", memo)
                entry["session_usage_total"] = usage
                meta["turns"].append(entry)
                save(meta)
                print(f"{task} {t}/{turns}", flush=True)
        meta.update(status="complete", end=pilot.timestamp())
        save(meta)
    except BaseException as exc:
        meta.update(status="error", error=str(exc), end=pilot.timestamp())
        save(meta)
        raise
    grade = replay(run)
    pilot.write_json(run / "grade.json", grade)
    return grade


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=["w1", "c1", "s1"])
    p.add_argument("run", type=Path)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--effort", choices=["low", "medium", "high"], default="low")
    p.add_argument("--replay", action="store_true")
    args = p.parse_args()
    if args.replay:
        if (
            json.loads((args.run / "manifest.json").read_text()).get("task_id")
            != args.task
        ):
            p.error("Selected task differs from run manifest")
        grade = replay(args.run.resolve())
    else:
        grade = run_task(args.task, args.run.resolve(), args.model, args.effort)
    print(json.dumps(grade, ensure_ascii=False))
