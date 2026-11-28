"""Run a blinded Catan league through Claude Code and the DeepSeek gateway."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import uuid
from datetime import datetime, timezone

from tasks.w1.claude import run_claude
from tasks.w1.gateway import Gateway, MODEL, URL
from .engine import IMAGE, connect
from .league import GAMES, SCHEDULE
from .public import BRIEFINGS, CONTEXT, PRACTICE
from .tools import ALLOWED, Table, broker

PROTOCOL = "catan-v1"
TURN_BLOCK = 7
SCOUT = {"game-1":("transfer-1",{"SHEEP":1}),"game-3":("update-1",{"SHEEP":1})}


def write(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")
    tmp.replace(path)


def scouting(table, game):
    name, offer = SCOUT[game]
    table.request("open",name=name)
    pos = table.request("view")["position"]
    outcome = table.request("act",position=pos,give=offer,take={"BRICK":1})
    relevant = [r for r in outcome["responses"] if r["player"]=="Ash" and r["action"] in ("ACCEPT_TRADE","REJECT_TRADE")]
    if len(relevant) != 1:
        raise RuntimeError("Practice trade observation is missing")
    action = relevant[0]["action"]
    detail = f"Separate practice observation: You proposed exchanging one SHEEP for one BRICK. Ash replied {action}."
    if game=="game-3":
        pos = outcome["state"]["position"]
        outcome = table.request("act",position=pos,give={"SHEEP":1,"WHEAT":1},take={"BRICK":1})
        if not any(r["player"]=="Ash" and r["action"]=="ACCEPT_TRADE" for r in outcome["responses"]):
            raise RuntimeError("Updated practice trade observation is missing")
        detail += " On that board Ash accepted a later offer of one SHEEP and one WHEAT for one BRICK."
    return detail


def run(dest, key, *, upstream=URL, image=IMAGE):
    dest = dest.resolve()
    dest.mkdir(mode=0o700,parents=True)
    trace = dest/"trace"
    trace.mkdir()
    meta = {"protocol":PROTOCOL,"model":MODEL,"thinking":"disabled","status":"running","blocks":[],
            "tables":{}, "start":datetime.now(timezone.utc).isoformat(), "schedule":SCHEDULE,
            "claude":subprocess.check_output(["claude","--version"],text=True).strip(),
            "revision":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
            "image":subprocess.check_output(["docker","image","inspect","-f","{{.Id}}",image],text=True).strip()}
    write(dest/"manifest.json",meta)
    try:
        with connect(meta["image"]) as engine, TemporaryDirectory(prefix="game-client-") as temp:
            table = Table(engine,trace/"mcp.jsonl",dest/"memory.json")
            with broker(table) as (address, token), Gateway(
                key,dest,allowed=ALLOWED,url=upstream,direct_response=True,timeout=135,
                private_markers=(str(Path(__file__).resolve().parents[2]),"score_state","/tasks/s4/grade.py"),
            ) as gateway:
                pythonpath = str(Path(__file__).resolve().parents[2])
                config = {"mcpServers":{"table":{"command":sys.executable,
                          "args":["-m","tasks.s4.tools",address,token],"env":{"PYTHONPATH":pythonpath}}}}
                session = None
                prev_calls = 0
                for name in SCHEDULE:
                    full_game = name in GAMES
                    if full_game:
                        client = Path(temp)/name
                        (client/"desk").mkdir(parents=True)
                        session = str(uuid.uuid4())
                        gateway.reasoning.clear()
                    league_note = scouting(table,name) if name in SCOUT else ""
                    initial = table.open(name)
                    meta["tables"][name] = {"initial_position":initial["position"],"initial_own_turns":initial["completed_own_turns"]}
                    if full_game:
                        first = BRIEFINGS[name]+("\n"+league_note if league_note else "")
                    else:
                        label, assignment = PRACTICE[name]
                        first = f"Practice table {label}. {assignment} The table is now open. Play the currently pending turn."
                    no_progress = 0
                    while not table.state["finished"]:
                        index = len(meta["blocks"])+1
                        prompt = (first if first else "Continue on the same table; use the live state and the earlier plan.")
                        n = TURN_BLOCK if full_game else 1
                        target = table.state["completed_own_turns"]+n
                        if full_game:
                            prompt += " Play up to "+str(n)+" further turns of your own seat, or until the match ends."
                        (trace/f"prompt-{index}.txt").write_text(prompt)
                        row = {"index":index,"table":name,"session":session,"target":target,
                               "first_session":full_game and bool(first),"first_tool":table.seq+1,
                               "start_position":table.state["position"]}
                        meta["blocks"].append(row)
                        write(dest/"manifest.json",meta)
                        table.set_goal(n)
                        calls = run_claude(dest,index,gateway,session,prompt,client,config=config,
                                           context=CONTEXT,allowed=ALLOWED,first_session=row["first_session"])
                        row.update(last_tool=table.seq, end_position=table.state["position"],
                                   calls=calls,first_request=prev_calls+1,last_request=gateway.count,
                                   segment_done=table.done())
                        prev_calls = gateway.count
                        write(dest/"manifest.json",meta)
                        print(f"{name} segment {index}: position {row['start_position']} → {row['end_position']}; "
                              f"{calls} provider attempts",flush=True)
                        if row["start_position"] == row["end_position"]:
                            no_progress += 1
                            if no_progress == 2:
                                # Leave a model stall observable without silently taking over any moves.
                                break
                        else:
                            no_progress = 0
                        if not full_game and table.done():
                            break
                        first = ""
                    final = table.request("end_state")
                    if not table.done() or (full_game and not table.state["finished"]):
                        meta["tables"][name]["stall"] = True
                    (trace/f"{name}-events.json").write_text(json.dumps(final,ensure_ascii=False)+"\n")
                    write(dest/"manifest.json",meta)
                    if (dest/"memory.json").exists():
                        shutil.copyfile(dest/"memory.json",trace/f"{name}-notes.json")
        meta["status"]="complete"
    except BaseException as exc:
        meta.update(status="error",error_type=type(exc).__name__)
        raise
    finally:
        meta["end"] = datetime.now(timezone.utc).isoformat()
        write(dest/"manifest.json",meta)
    return meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest",type=Path)
    p.add_argument("--image",default=IMAGE)
    p.add_argument("--upstream",default=URL,help="Chat Completions endpoint operated by the evaluator")
    args = p.parse_args()
    key = os.environ.get("ARK_API_KEY", "")
    if not key:
        p.error("Set ARK_API_KEY in the host or use the team's approved relay credential")
    run(args.dest,key,upstream=args.upstream,image=args.image)


if __name__ == "__main__":
    main()
