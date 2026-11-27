"""A continuous equipment desk serving several interleaved regional leagues."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from random import Random
from statistics import mean
import subprocess
import tempfile
import uuid

from w1.claude import run_claude
from w1.gateway import Gateway, MODEL, URL
from .pilot import write
from .relay import Season, WEIGHTS, decode, grade, submit
from .relay_pilot import final_result

RULES = """你是跨赛区联赛器材总台领队，各区轮流送件，全程连续值班。同一队号、单号在不同赛区独立。
各区有八班。开幕册是底册，只采用本区的批准单，草案无效。全季批准适用于各赛段，专项仅适用于所列赛段。同队同字段取当时可用的最大单号。撤回从发布时起排除原单，回退到其余适用单或底册；不改写已结束的赛段。
本区第4班预选、第5班邀请、第7班决赛。第8班补历史凭证，以订单所列赛段当时的审批为准，即便该队当时没有订购。订单附过期的季前仓单供核对。
每班只交一个 JSON 对象。orders 以本次订单队号作键，每队交四项数组 [器材,箱签,领牌员,交接台]。按实际配发分别验收器材与箱签、领牌员与交接台。收文班可以回复 {}。可用 note 在对话里整理必要信息。后续按赛区和队号查阅自己的历史；总台不自动摘抄笔记。"""


class Circuit:
    def __init__(self, seed, variant, desks, level):
        if not 2 <= desks <= 24:
            raise ValueError("desks must be between 2 and 24")
        self.seasons = {
            f"区{i + 1:02}": Season(seed * 100 + i, level, variant, "warehouse")
            for i in range(desks)
        }
        self.schedule = []
        for stage in range(1, 9):
            names = list(self.seasons)
            Random(f"circuit/v1/{seed}/{stage}").shuffle(names)
            self.schedule.extend((name, stage) for name in names)

    def prompt(self, turn):
        desk, stage = self.schedule[turn - 1]
        season = self.seasons[desk]
        # Exclude the short edition's handover-specific note and capacity notice.
        _, material = season.prompt(stage, "", "continuous").split("（空）\n", 1)
        return f"总台第{turn}轮｜{desk}第{stage}班\n" + material

    def receipt(self, turn, command):
        desk, stage = self.schedule[turn - 1]
        receipt = submit(self.seasons[desk], stage, command, "")
        return {
            "desk": desk,
            "stage": stage,
            "booked": receipt["booked"],
            "rejected": receipt["rejected"],
        }

    def score(self, receipts):
        if len(receipts) != len(self.schedule):
            raise ValueError("incomplete season")
        by_desk = defaultdict(dict)
        for (desk, stage), receipt in zip(self.schedule, receipts):
            if (receipt["desk"], receipt["stage"]) != (desk, stage):
                raise ValueError("receipt at wrong desk or stage")
            by_desk[desk][str(stage)] = receipt
        scores = {
            desk: grade(season, by_desk[desk]) for desk, season in self.seasons.items()
        }
        groups = {
            str(k): mean(x["groups"][str(k)] for x in scores.values()) for k in WEIGHTS
        }
        return {
            "total": round(sum(groups.values()), 3),
            "groups": groups,
            "desks": scores,
        }


def read_command(text, version):
    if version == 1:
        return decode(text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("请提交 JSON 对象")
    obj = (
        decode(text[start : end + 1])
        if "```" not in text[start : end + 1]
        else decode(text)
    )
    if obj and all(k.isascii() and k.isdigit() for k in obj):
        return {"orders": obj}
    if obj.keys() - {"orders", "note"}:
        raise ValueError("单据须有 orders 或 note 字段，或直接以队号作键")
    return obj


def audit(run):
    meta = json.loads((run / "manifest.json").read_text())
    circuit = Circuit(meta["seed"], meta["variant"], meta["desks"], meta["level"])
    turns = len(circuit.schedule)
    if len(meta["calls"]) != turns:
        raise ValueError("missing scheduled turns")
    trace = run / "trace"
    packets = defaultdict(list)
    counts = Counter()
    for path in sorted(trace.glob("api-*.json")):
        packet = json.loads(path.read_text())
        packets[packet["turn"]].append(packet)
    if set(packets) != {idx for calls in meta["calls"] for idx in calls}:
        raise ValueError("unexpected or missing provider calls")
    receipts = []
    public_systems = (
        RULES,
        "You are a Claude agent, built on Anthropic's Claude Agent SDK.\n" + RULES,
    )
    public_history = defaultdict(list)
    ids = set()
    for t, calls in enumerate(meta["calls"], 1):
        prompt = circuit.prompt(t)
        desk, _ = circuit.schedule[t - 1]
        session = meta.get("regional_sessions", {}).get(desk, meta["session"])
        public_history[session].append(prompt)
        if (
            calls not in ([t], [t, t + turns])
            or (trace / f"prompt-{t}.txt").read_text() != prompt
        ):
            raise ValueError(f"R{t}: wrong calls or material")
        receipt = circuit.receipt(t, {})
        for idx in calls:
            answer = final_result(trace / f"turn-{idx}.jsonl")
            events = [
                json.loads(line)
                for line in (trace / f"turn-{idx}.jsonl").read_text().splitlines()
                if line.strip()
            ]
            if not any(
                e.get("type") == "result" and e.get("session_id") == session
                for e in events
            ):
                raise ValueError(f"R{t}: unexpected Claude session")
            counts["compact_events"] += sum(
                e.get("subtype") == "compact_boundary" for e in events
            )
            matched = False
            for packet in packets[idx]:
                req = packet["request"]
                msgs = req["messages"]
                if (
                    req["model"] != meta["model"]
                    or req.get("tools")
                    or [m["content"] for m in msgs if m["role"] == "system"]
                    not in ([public_systems[0]], [public_systems[1]])
                    or (idx == t and msgs[-1]["content"] != prompt)
                ):
                    raise ValueError(f"R{t}: unexpected API prompt")
                reply = packet.get("response", {})
                usage = reply.get("usage")
                if not usage:
                    counts["missing_usage"] += 1
                    continue
                if reply["model"] != meta["model"]:
                    raise ValueError("wrong provider model")
                if not reply.get("id") or reply["id"] in ids:
                    raise ValueError("missing or duplicate provider response")
                ids.add(reply["id"])
                n = usage["prompt_tokens"]
                counts["input"] += n
                counts["output"] += usage["completion_tokens"]
                counts["peak_input"] = max(counts["peak_input"], n)
                counts["cached_input"] += (
                    usage.get("prompt_tokens_details") or {}
                ).get("cached_tokens", 0)
                counts["calls"] += 1
                if (
                    reply["choices"][0]["message"].get("content") or ""
                ).strip() == answer.strip():
                    if idx == t and not matched:
                        counts["first_submission_input"] += n
                        visible = {m["content"] for m in msgs if m["role"] == "user"}
                        if all(p in visible for p in public_history[session]):
                            counts["turns_with_full_public_history"] += 1
                    matched = True
            if not matched:
                raise ValueError(f"R{t}: no matching upstream result")
            try:
                receipt = circuit.receipt(
                    t, read_command(answer, meta.get("parser_version", 1))
                )
            except ValueError:
                continue
            if idx != calls[-1]:
                raise ValueError("valid submission was retried")
        if receipt != json.loads((run / f"receipt-{t}.json").read_text()):
            raise ValueError(f"R{t}: receipt mismatch")
        receipts.append(receipt)
    result = circuit.score(receipts)
    result["usage"] = dict(counts)
    return result


def run_one(dest, model, seed, variant, desks, level, history="continuous"):
    circuit = Circuit(seed, variant, desks, level)
    total = len(circuit.schedule)
    prefix = "regional-" if history == "regional" else ""
    run = dest / f"{prefix}D{desks}-L{level}-{seed}-{variant}-{model}"
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    (run / "trace").mkdir()
    deep = model == "deepseek"
    name = MODEL if deep else "qwen3.8-flash"
    key = os.environ["ARK_API_KEY" if deep else "DEEPSEEK_API_KEY"]
    url = (
        URL
        if deep
        else os.environ["DEEPSEEK_BASE_URL"].rstrip("/") + "/chat/completions"
    )
    session = str(uuid.uuid4())
    sessions = (
        {desk: str(uuid.uuid4()) for desk in circuit.seasons}
        if history == "regional"
        else {}
    )
    meta = dict(
        parser_version=2,
        history=history,
        regional_sessions=sessions,
        seed=seed,
        variant=variant,
        desks=desks,
        level=level,
        model=name,
        session=session,
        status="running",
        calls=[],
        git=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        cli=subprocess.check_output(["claude", "--version"], text=True).strip(),
    )
    write(run / "manifest.json", meta)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="circuit-") as tmp,
            Gateway(
                key,
                run,
                3 * total,
                allowed=(),
                model=name,
                url=url,
                timeout=600,
                direct_response=True,
            ) as gateway,
        ):
            client = Path(tmp)
            (client / "desk").mkdir()
            for t in range(1, total + 1):
                prompt = circuit.prompt(t)
                (run / "trace" / f"prompt-{t}.txt").write_text(prompt)
                desk, stage = circuit.schedule[t - 1]
                session_id = sessions.get(desk, session)
                fresh = stage == 1 if sessions else t == 1
                calls = []
                for idx in (t, t + total):
                    calls.append(idx)
                    run_claude(
                        run,
                        idx,
                        gateway,
                        session_id,
                        prompt,
                        client,
                        config={"mcpServers": {}},
                        context=RULES,
                        allowed=(),
                        first_session=fresh and idx == t,
                    )
                    try:
                        receipt = circuit.receipt(
                            t,
                            read_command(
                                final_result(run / "trace" / f"turn-{idx}.jsonl"), 2
                            ),
                        )
                        break
                    except ValueError as exc:
                        prompt = f"单据格式未接收：{exc}。请重交本轮单据。"
                else:
                    receipt = circuit.receipt(t, {})
                write(run / f"receipt-{t}.json", receipt)
                meta["calls"].append(calls)
                write(run / "manifest.json", meta)
        result = audit(run)
        write(run / "grade.json", result)
        meta["status"] = "complete"
        print(run.name, result["total"], result["usage"], flush=True)
    except Exception as exc:
        meta.update(status="error", error=str(exc).replace(key, "[redacted]"))
        raise
    finally:
        write(run / "manifest.json", meta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--variants", nargs="+", choices=["A", "B"], default=["A", "B"])
    parser.add_argument(
        "--models",
        nargs="+",
        choices=["deepseek", "qwen"],
        default=["deepseek", "qwen"],
    )
    parser.add_argument("--desks", type=int, required=True)
    parser.add_argument("--level", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--history", choices=["continuous", "regional"], default="continuous"
    )
    args = parser.parse_args()
    with ThreadPoolExecutor(args.workers) as pool:
        jobs = [
            pool.submit(
                run_one,
                args.dest.resolve(),
                m,
                s,
                v,
                args.desks,
                args.level,
                args.history,
            )
            for s in args.seeds
            for v in args.variants
            for m in args.models
        ]
        for job in jobs:
            job.result()


if __name__ == "__main__":
    main()
