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
from .relay import Season, WEIGHTS, decode, grade, submit, unique_fields
from .relay_pilot import final_result

RULES = """你是跨赛区联赛器材总台领队，各区轮流送件，全程连续值班。同一队号、单号在不同赛区独立。
各区有八班。开幕册是底册，只采用本区的批准单，草案无效。全季批准适用于各赛段，专项仅适用于所列赛段。同队同字段取当时可用的最大单号。撤回从发布时起排除原单，回退到其余适用单或底册；不改写已结束的赛段。
本区第4班预选、第5班邀请、第7班决赛。第8班补历史凭证，以订单所列赛段当时的审批为准，即便该队当时没有订购。订单附过期的季前仓单供核对。
每班只交一个 JSON 对象。orders 以本次订单队号作键，每队交四项数组 [器材,箱签,领牌员,交接台]。按实际配发分别验收器材与箱签、领牌员与交接台。收文班可以回复 {}。可用 note 在对话里整理必要信息。后续按赛区和队号查阅自己的历史；总台不自动摘抄笔记。"""


REGISTER_PHASE = {1: "预选", 2: "决赛", 3: "邀请", 6: "决赛"}
SINGLE_RULES = RULES.replace("收文班可以回复 {}。", "收文班用 register 按队号登记所列赛段的四项配置，顺序与订单相同，以本班截止时已收到的有效文件为准。登记不产生配发。")


class Circuit:
    def __init__(self, seed, variant, desks, level, qualifiers=0, *, version=2):
        if version not in (1, 2) or (version == 2 and variant != "A"):
            raise ValueError("invalid circuit edition")
        self.version = version
        self.rules = SINGLE_RULES if version == 2 else RULES
        if not 2 <= desks <= 24:
            raise ValueError("desks must be between 2 and 24")
        if not 0 <= qualifiers < desks:
            raise ValueError("small district count must be below total districts")
        self.seasons = {
            f"区{i + 1:02}": Season(
                seed * 100 + i,
                1 if i >= desks - qualifiers else level,
                variant,
                "warehouse",
            )
            for i in range(desks)
        }
        self.schedule = []
        for stage in range(1, 9):
            names = list(self.seasons)
            Random(f"circuit/v1/{seed}/{stage}").shuffle(names)
            self.schedule.extend((name, stage) for name in names)

    def register_teams(self, desk, stage):
        season = self.seasons[desk]
        rng = Random(f"register/v1/{season.seed}/{stage}")
        phase = REGISTER_PHASE[stage]
        withdrawn = sorted({d.team for d in season.notices
                            if season.withdrawn.get(d.number) == stage and d.scope in ("全季", phase)})
        approved = sorted({d.team for d in season.notices if d.turn == stage
                           and d.official and d.scope in ("全季", phase)})
        first = rng.choice(withdrawn or approved or season.teams)
        return [first, rng.choice([t for t in season.teams if t != first])]

    def prompt(self, turn, history="continuous", memo=""):
        desk, stage = self.schedule[turn - 1]
        season = self.seasons[desk]
        # Exclude the short edition's handover-specific note and capacity notice.
        _, material = season.prompt(stage, "", "continuous").split("（空）\n", 1)
        prompt = f"总台第{turn}轮｜{desk}第{stage}班\n" + material
        if self.version == 2 and stage in REGISTER_PHASE:
            teams = "、".join(self.register_teams(desk, stage))
            prompt += f"\n登记任务：{REGISTER_PHASE[stage]}，队号 {teams}。请在 register 中填入截至本班的配置。"
        halfway = len(self.schedule) // 2
        if history == "handover":
            if turn in (1, halfway):
                prompt += f"\n换班安排：第{halfway}轮末在该轮 JSON 的 note 内提交全区摘要，最多保留前 5500 个字符。下一轮新开会话，仅这份摘要随队。"
            elif turn == halfway + 1:
                prompt += "\n上一班实际留存的摘要：\n" + (memo or "（空）")
        return prompt

    def receipt(self, turn, command, history="continuous"):
        desk, stage = self.schedule[turn - 1]
        receipt = submit(self.seasons[desk], stage, command, "")
        result = {
            "desk": desk,
            "stage": stage,
            "booked": receipt["booked"],
            "rejected": receipt["rejected"],
        }

        if self.version == 2 and stage in REGISTER_PHASE:
            rows = command.get("register", {})
            if not isinstance(rows, dict):
                raise ValueError("register 须为按队号填写的对象")
            result["register"] = {}
            for team in self.register_teams(desk, stage):
                row = rows.get(team)
                if isinstance(row, list) and 0 < len(row) <= 4:
                    result["register"][team] = [
                        str(v).strip() if type(v) in (str, int) else None for v in row
                    ] + [None] * (4 - len(row))

        if history == "handover" and turn == len(self.schedule) // 2:
            note = command.get("note", "")
            result.update(memo=note[:5500], memo_length=len(note))
        return result

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
        if self.version == 2:
            for desk, details in scores.items():
                season = self.seasons[desk]
                groups = {stage: value * 0.70 for stage, value in details["groups"].items()}
                checks = []
                for stage, phase in REGISTER_PHASE.items():
                    hits = 0
                    submitted = by_desk[desk][str(stage)]["register"]
                    for team in self.register_teams(desk, stage):
                        expected = season.expected(team, phase, as_of=stage)
                        actual = submitted.get(team)
                        correct = [actual is not None and actual[i] == v for i, v in enumerate(expected)]
                        hits += sum(correct)
                        checks.append(dict(stage=stage, phase=phase, team=team,
                                           actual=actual, expected=expected, correct=correct))
                    groups[str(stage)] = 7.5 * hits / 8
                details.update(register=checks, groups=groups, total=round(sum(groups.values()), 3))
        groups = {
            k: mean(d["groups"][k] for d in scores.values())
            for k in next(iter(scores.values()))["groups"]
        }
        result = dict(total=round(sum(groups.values()), 3), groups=groups, desks=scores)
        if self.version == 2:
            result["registration_points"] = round(sum(groups[str(s)] for s in REGISTER_PHASE), 3)
            result["outcome_points"] = round(sum(groups[str(s)] for s in WEIGHTS), 3)
        return result


def read_command(text, version):
    if version == 1:
        return decode(text)
    if version not in (2, 3):
        raise ValueError("unknown parser version")
    if version == 3:
        try:
            whole = json.loads(text)
        except (ValueError, RecursionError):
            pass
        else:
            if not isinstance(whole, dict):
                raise ValueError("请提交 JSON 对象")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("请提交 JSON 对象")
    try:
        obj = json.loads(text[start : end + 1], object_pairs_hook=unique_fields)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("请只交一个完整的 JSON 对象") from exc
    if obj and all(k.isascii() and k.isdigit() for k in obj):
        return {"orders": obj}
    allowed = {"orders", "note", "register"} if version == 3 else {"orders", "note"}
    if obj.keys() - allowed:
        raise ValueError("单据须有 orders 或 note 字段，或直接以队号作键")
    return obj


def audit(run):
    meta = json.loads((run / "manifest.json").read_text())
    circuit = Circuit(
        meta["seed"],
        meta["variant"],
        meta["desks"],
        meta["level"],
        meta.get("qualifiers", 0),
        version=meta.get("score_version", 1),
    )
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
        circuit.rules,
        "You are a Claude agent, built on Anthropic's Claude Agent SDK.\n" + circuit.rules,
    )
    public_history = defaultdict(list)
    ids = set()
    history = meta.get("history", "continuous")
    if history == "regional":
        sessions = meta["regional_sessions"]
        if set(sessions) != set(circuit.seasons) or len(set(sessions.values())) != len(
            sessions
        ):
            raise ValueError("invalid regional sessions")
    if history == "handover" and meta["next_session"] == meta["session"]:
        raise ValueError("handover reused original session")
    memo = ""
    for t, calls in enumerate(meta["calls"], 1):
        prompt = circuit.prompt(t, history, memo)
        desk, _ = circuit.schedule[t - 1]
        session = meta.get("regional_sessions", {}).get(desk, meta["session"])
        if history == "handover" and t > turns // 2:
            session = meta["next_session"]
        fresh = session not in public_history
        public_history[session].append(prompt)
        if (
            calls not in ([t], [t, t + turns])
            or (trace / f"prompt-{t}.txt").read_text() != prompt
        ):
            raise ValueError(f"R{t}: wrong calls or material")
        receipt = circuit.receipt(t, {}, history)
        expected_prompt = prompt
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
                    (
                        fresh
                        and idx == t
                        and [m["role"] for m in msgs] != ["system", "user"]
                    )
                    or req["model"] != meta["model"]
                    or req.get("tools")
                    or [m["content"] for m in msgs if m["role"] == "system"]
                    not in ([public_systems[0]], [public_systems[1]])
                    or ((idx == t or circuit.version == 2) and msgs[-1] != {"role": "user", "content": expected_prompt})
                ):
                    raise ValueError(f"R{t}: unexpected API prompt")
                reply = packet.get("response", {})
                usage = reply.get("usage")
                if not usage:
                    counts["missing_usage"] += 1
                    continue
                direct = (
                    req.get("thinking") == {"type": "disabled"}
                    if req["model"] == MODEL
                    else req["model"] == "qwen3.8-flash"
                    and req.get("enable_thinking") is False
                    and req.get("chat_template_kwargs", {}).get("enable_thinking")
                    is False
                )
                if req["model"] == "gpt-6.1-sol":
                    if req.get("reasoning_effort") != "low":
                        raise ValueError("expected low reasoning effort")
                elif (
                    not direct
                    or reply["choices"][0]["message"].get("reasoning_content")
                    or (usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"
                    )
                ):
                    raise ValueError("provider reasoning configuration differs")
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
                    t, read_command(answer, meta.get("parser_version", 1)), history
                )
            except ValueError as exc:
                if circuit.version == 2 and calls == [t]:
                    raise ValueError(f"R{t}: missing format retry") from exc
                expected_prompt = f"单据格式未接收：{exc}。请重交本轮单据。"
                continue
            if idx != calls[-1]:
                raise ValueError("valid submission was retried")
        if receipt != json.loads((run / f"receipt-{t}.json").read_text()):
            raise ValueError(f"R{t}: receipt mismatch")
        memo = receipt.get("memo", memo)
        receipts.append(receipt)
    result = circuit.score(receipts)
    result["usage"] = dict(counts)
    return result


def run_one(
    dest, model, seed, variant, desks, level, history="continuous", qualifiers=0
):
    circuit = Circuit(seed, variant, desks, level, qualifiers)
    total = len(circuit.schedule)
    prefix = history + "-" if history != "continuous" else ""
    if qualifiers:
        prefix += f"Q{qualifiers}-"
    run = dest / f"{prefix}D{desks}-L{level}-{seed}-{variant}-{model}"
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    (run / "trace").mkdir()
    if model == "deepseek":
        name, key, url = MODEL, os.environ["ARK_API_KEY"], URL
    else:
        gpt = model == "gpt-6.1-sol"
        prefix = "OPENAI" if gpt else "DEEPSEEK"
        name = model if gpt else "qwen3.8-flash"
        key = os.environ[f"{prefix}_API_KEY"]
        url = os.environ[f"{prefix}_BASE_URL"].rstrip("/") + "/chat/completions"
    session = str(uuid.uuid4())
    sessions = (
        {desk: str(uuid.uuid4()) for desk in circuit.seasons}
        if history == "regional"
        else {}
    )
    meta = dict(
        parser_version=3,
        score_version=2,
        history=history,
        regional_sessions=sessions,
        seed=seed,
        variant=variant,
        desks=desks,
        qualifiers=qualifiers,
        level=level,
        model=name,
        session=session,
        status="running",
        calls=[],
        git=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True
        ).strip(),
        cli=subprocess.check_output(["claude", "--version"], text=True).strip(),
    )
    if history == "handover":
        meta["next_session"] = str(uuid.uuid4())
    memo = ""
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
                direct_response=model != "gpt-6.1-sol",
            ) as gateway,
        ):
            client = Path(tmp)
            (client / "desk").mkdir()
            for t in range(1, total + 1):
                prompt = circuit.prompt(t, history, memo)
                (run / "trace" / f"prompt-{t}.txt").write_text(prompt)
                desk, stage = circuit.schedule[t - 1]
                session_id = sessions.get(desk, session)
                fresh = stage == 1 if sessions else t == 1
                if history == "handover" and t > total // 2:
                    session_id = meta["next_session"]
                    fresh = t == total // 2 + 1
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
                        context=circuit.rules,
                        allowed=(),
                        first_session=fresh and idx == t,
                    )
                    try:
                        receipt = circuit.receipt(
                            t,
                            read_command(
                                final_result(run / "trace" / f"turn-{idx}.jsonl"), 3
                            ),
                            history,
                        )
                        break
                    except ValueError as exc:
                        prompt = f"单据格式未接收：{exc}。请重交本轮单据。"
                else:
                    receipt = circuit.receipt(t, {}, history)
                memo = receipt.get("memo", memo)
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
    parser.add_argument(
        "--models",
        nargs="+",
        choices=["deepseek", "qwen", "gpt-6.1-sol"],
        default=["deepseek"],
    )
    parser.add_argument("--desks", type=int, required=True)
    parser.add_argument(
        "--qualifiers", type=int, default=0, help="number of small six-team districts"
    )
    parser.add_argument("--level", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--history",
        choices=["continuous", "regional", "handover"],
        default="continuous",
    )
    args = parser.parse_args()
    with ThreadPoolExecutor(args.workers) as pool:
        jobs = [
            pool.submit(
                run_one,
                args.dest.resolve(),
                m,
                s,
                "A",
                args.desks,
                args.level,
                args.history,
                args.qualifiers,
            )
            for s in args.seeds
            for m in args.models
        ]
        for job in jobs:
            job.result()


if __name__ == "__main__":
    main()
