"""Run a fixed public LongWorkMem task using native Codex threads and Docker."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess

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
    prefix, tools = ("office", office.TOOLS) if task == "w1" else ("workshop", [sandbox.TOOL])
    return [{**s, "name":prefix+"_"+s["name"]} for s in tools]


def recorded_turn(run, idx, thread, prompt, allowed):
    path = run/"trace"/f"turn-{idx}.jsonl"
    calls = {}
    final = None
    started = completed = False
    for line in path.read_text().splitlines():
        row = json.loads(line)
        m = row["message"]
        p = m.get("params", {})
        method = m.get("method")
        if method == "turn/start":
            if started or p["threadId"] != thread or p["input"] != [dict(type="text",text=prompt)]:
                raise ValueError("Codex turn input differs")
            started = True
        if method in ("item/completed", "item/tool/call", "turn/completed") and p["threadId"] != thread:
            raise ValueError("Codex event from wrong session")
        if method == "item/tool/call":
            if p["tool"] not in allowed or m["id"] in calls:
                raise ValueError("Unexpected Codex tool")
            calls[m["id"]] = False
        if row["direction"] == "send" and "result" in m:
            if m["id"] not in calls or calls[m["id"]]:
                raise ValueError("Unmatched Codex tool response")
            calls[m["id"]] = True
        if method == "item/completed":
            item = p["item"]
            if item["type"] == "agentMessage":
                final = item["text"]
            elif item["type"] not in ("userMessage","reasoning","dynamicToolCall","contextCompaction","plan"):
                raise ValueError("Unexpected native action "+item["type"])
        if method == "turn/completed":
            completed = p["turn"]["status"] == "completed"
    if not started or not completed or final is None or not all(calls.values()):
        raise ValueError("Incomplete native Codex turn")
    return final


def verify_threads(run, meta, task, shifts):
    threads = [json.loads(line) for line in (run/"trace/threads.jsonl").read_text().splitlines()]
    allowed = [s["name"] for s in specs_for(task)]
    if len(threads) != len(shifts) or len({x["thread"] for x in threads}) != len(shifts):
        raise ValueError("Wrong number of Codex sessions")
    if any(x["model"] != meta["model"] or x["tools"] != allowed or x["effort"] != meta["effort"] for x in threads):
        raise ValueError("Unexpected model, tools or reasoning setting")
    return dict(zip(shifts,(x["thread"] for x in threads))), allowed


def replay(run):
    meta = json.loads((run/"manifest.json").read_text())
    task = meta["task_id"]
    shifts = {"w1":[1], "c1":[1,5,7], "s1":[1,41]}[task]
    threads, allowed = verify_threads(run, meta, task, shifts)
    count = {"w1":9, "c1":7, "s1":80}[task]
    if [x["turn"] for x in meta["turns"]] != list(range(1,count+1)):
        raise ValueError("Incomplete schedule")
    circuit = Circuit(PUBLIC_SEED,PUBLIC_VARIANT,10,2,2,version=3) if task == "s1" else None
    receipts = []
    memo = ""
    for t, entry in enumerate(meta["turns"],1):
        session = threads[max(k for k in shifts if k <= t)]
        prompt = (run/"trace"/f"prompt-{t}.txt").read_text()
        if entry["session"] != session:
            raise ValueError("Incorrect handover")
        if circuit and prompt != circuit.prompt(t,"handover",memo):
            raise ValueError("Incorrect S1 prompt or memo")
        attempts = entry["attempts"]
        if attempts != [t] and not (circuit and attempts == [t,t+count]):
            raise ValueError("Unexpected attempts")
        for idx in attempts:
            answer = recorded_turn(run,idx,session,prompt,allowed)
            if circuit:
                try:
                    receipt = circuit.submission(t,read_command(answer,4),"handover")
                except ValueError as exc:
                    if len(attempts) == 1:
                        raise ValueError("Missing format retry") from exc
                    prompt = f"单据格式未接收：{exc}。请重交本轮单据。"
                    receipt = circuit.receipt(t,{},"handover")
                else:
                    if idx != attempts[-1]:
                        raise ValueError("Valid answer retried")
        if circuit:
            if receipt != json.loads((run/f"receipt-{t}.json").read_text()):
                raise ValueError("S1 receipt mismatch")
            memo = receipt.get("memo",memo)
            receipts.append(receipt)
    if circuit:
        return circuit.score(receipts)
    if task == "w1":
        return advanced.grade(run,details=True)
    return settlement_grade.grade(run,"docker")


def run_task(task, run, model, effort):
    seed, v = PUBLIC_SEED, PUBLIC_VARIANT
    if task == "w1":
        work = prepare(run)
    else:
        run.mkdir(parents=True,mode=0o700,exist_ok=False)
        (run/"trace").mkdir()
        work = run/"work"
        if task == "c1":
            for name in ("input",*sandbox.WRITABLE):
                (work/name).mkdir(parents=True)
    save = lambda obj: pilot.write_json(run/"manifest.json",obj)
    meta = dict(task_id=task, harness="codex-app-server", model=model, effort=effort,
                seed=seed, variant=v, protocol=PROTOCOL, condition="public", backend="docker",
                limit=None, status="running", turns=[], start=pilot.timestamp(),
                codex=subprocess.check_output(["codex","--version"],text=True).strip(),
                git=subprocess.check_output(["git","rev-parse","HEAD"],cwd=Path(__file__).parent,text=True).strip())
    save(meta)
    try:
        engine_context = nullcontext((None,None))
        if task == "w1":
            meta.update(task="W1-advanced",level=8,erp_window=False,docker_image=docker_image(),
                        isolation=isolation_check(work,"docker"))
            context = CONTEXT+"本办公室支持使用 soffice --headless 在副本上实际重算 Excel。"
            turns, shifts = 9, (1,)
        elif task == "c1":
            meta.update(mode="settlement",level=3,image=sandbox.image_id(),rotation_turns=[5,7],
                        withdraw_handover=True,dispatch_window=None,isolation=pilot.check_boundary(work,"docker"))
            context = pilot.CONTEXT
            turns, shifts = 7, (1,5,7)
        else:
            engine_context = open_engine(seed,v,10,2,2)
            meta.update(level=2,desks=10,qualifiers=2,score_version=3,parser_version=4,history="handover")
            context = Circuit(seed,v,10,2,2,version=3).rules
            turns, shifts = 80, (1,41)
        with engine_context as (engine,image), Client(run,model,effort) as client:
            if image:
                meta["engine_image"] = image
            memo = ""
            for t in range(1,turns+1):
                if t in shifts:
                    client.start(context,specs_for(task))
                entry = dict(turn=t,session=client.thread,attempts=[t])
                if task == "w1":
                    prompt = advanced.release(work,t,v,8,seed,erp_window=False)
                    entry["public_digest"] = advanced.public_digest(work,prompt)
                elif task == "c1":
                    prompt = pilot.release_turn(work,t,v,seed,3,None,True)
                else:
                    prompt = exchange(engine,"prompt",t,"handover",memo)
                (run/"trace"/f"prompt-{t}.txt").write_text(prompt)
                def tool(name, args):
                    if name == "workshop_shell":
                        return sandbox.shell(work,args["command"],"docker",image=meta["image"])
                    if name == "office_shell":
                        return office.shell(work,args["command"],"docker",image=meta["docker_image"])
                    return {"receipt":office.act(run,t,name.removeprefix("office_"),**args)}
                answer,usage = client.turn(t,prompt,tool if task != "s1" else None)
                if task == "w1":
                    freeze(run,t)
                elif task == "c1":
                    entry["omissions"] = freeze_desk(work,run/"snapshots"/str(t))
                else:
                    try:
                        receipt = exchange(engine,"submit",t,read_command(answer,4),"handover")
                    except ValueError as exc:
                        idx = t+turns
                        entry["attempts"].append(idx)
                        answer,usage = client.turn(idx,f"单据格式未接收：{exc}。请重交本轮单据。")
                        try:
                            receipt = exchange(engine,"submit",t,read_command(answer,4),"handover")
                        except ValueError:
                            receipt = exchange(engine,"empty",t,"handover")
                    pilot.write_json(run/f"receipt-{t}.json",receipt)
                    memo = receipt.get("memo",memo)
                entry["session_usage_total"] = usage
                meta["turns"].append(entry)
                save(meta)
                print(f"{task} {t}/{turns}",flush=True)
        meta.update(status="complete",end=pilot.timestamp())
        save(meta)
    except BaseException as exc:
        meta.update(status="error",error=str(exc),end=pilot.timestamp())
        save(meta)
        raise
    grade = replay(run)
    pilot.write_json(run/"grade.json",grade)
    return grade


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task",choices=["w1","c1","s1"])
    p.add_argument("run",type=Path)
    p.add_argument("--model",default=MODEL)
    p.add_argument("--effort",choices=["low","medium","high"],default="low")
    p.add_argument("--replay",action="store_true")
    args = p.parse_args()
    if args.replay:
        grade = replay(args.run.resolve())
    else:
        grade = run_task(args.task,args.run.resolve(),args.model,args.effort)
    print(json.dumps(grade,ensure_ascii=False))
