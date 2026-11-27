"""Fresh-session reserve-booking contrast with and without the previously issued mandates."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import uuid

from . import advanced, advanced_memory as memory
from .controls import seed_digest, write_json
from .gateway import Gateway, MODEL
from .pilot import blinded_office, claude_turn, docker_image, isolation_check, provider, source_hashes
from .runstate import freeze
from .scoring_tables import Table


def fixture(work, seed, variant, turn):
    reminders = []
    for t in range(1, turn+1):
        advanced.release(work, t, variant, 7, seed)
        if t in (1,4,6):
            # Only previous business instructions may be added in the reminder condition.
            reminders.append(memory.release(work, t, seed))
        if t in memory.DATES and t < turn:
            memory.reference(work.parent, t, variant, 7, seed)
    return reminders


def assess(run, seed, variant, turn, prior):
    actual = memory.index(Table(run/"snapshots"/str(turn)/memory.form(turn)).rows)
    want = memory.posting(memory.cases(turn,seed),turn,memory.mandate(seed),
                          {"A":"2025-07-16","B":"2025-08-16"}[variant],prior)
    keys = {(r["office"],r["case"]) for r in want}
    denominator = len(keys | actual.keys())
    fields = ("project","desk","authority","decision","target","change")
    matches = {f:sum(len(actual.get((r["office"],r["case"]),[])) == 1 and
                     memory.equal(actual[r["office"],r["case"]][0],r,[f]) for r in want) for f in fields}
    complete = sum(len(actual.get((r["office"],r["case"]),[])) == 1 and
                   memory.equal(actual[r["office"],r["case"]][0],r,fields) for r in want)
    return dict(cases=denominator, correct_by_field=matches, all_fields=complete, scorer_version="reserve/1.3")


def play(run, seed, variant, turn, reminder, model, url, key):
    with blinded_office(run, "docker") as work:
        instructions = fixture(work, seed, variant, turn)
        prompt = (f"今天是{memory.DATES[turn]}。你只负责今日争议清册的预留入账，其余工作已由同事接手。"
                  "请根据已交接的业务材料完成本次申报，自行按需查阅之前的入账留底。")
        if reminder:
            prompt += "\n主管此前的三次授权原文如下。\n"+"\n".join(instructions)
        from .erp_window import notice
        prompt += notice(turn)
        prior = memory.filed_amounts(work/"out"/memory.form(8)) if turn == 9 else {}
        session = str(uuid.uuid4())
        state = run/"manifest.json"
        manifest = dict(task="W1-reserve-control", status="running", level=7, seed=seed, variant=variant,
                        arm="reminder" if reminder else "current", turn=turn, model=model, backend="docker",
                        claude=subprocess.check_output(["claude","--version"],text=True).strip(),
                        docker_image=docker_image(), session=session, limit=40, turns=[], file_hashes=source_hashes(),
                        office_digest=seed_digest(work))
        write_json(state, manifest)
        try:
            manifest["isolation"] = isolation_check(work, "docker")
            (run/"trace"/f"prompt-{turn}.txt").write_text(prompt)
            with TemporaryDirectory() as tmp, Gateway(key, run, 40, model=model, url=url) as gw:
                client = Path(tmp)
                (client/"desk").mkdir()
                calls = claude_turn(run,turn,"docker",gw,session,prompt,client,first_session=True,image_id=manifest["docker_image"])
            freeze(run,turn)
            write_json(run/"reserve-result.json", assess(run, seed, variant, turn, prior))
            manifest.update(status="complete", turns=[dict(turn=turn,upstream_calls=calls)])
        except Exception as exc:
            manifest.update(status="error",error=str(exc))
            raise
        finally:
            write_json(state,manifest)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest",type=Path)
    p.add_argument("--model",choices=[MODEL,"qwen3.8-flash"],default=MODEL)
    p.add_argument("--variant",choices=["A","B"],default="A")
    p.add_argument("--seed",type=int,default=431)
    p.add_argument("--turn",type=int,choices=[8,9],default=8)
    args=p.parse_args()
    url,key=provider(args.model)
    args.dest.mkdir(exist_ok=False,parents=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(play,args.dest/arm,args.seed,args.variant,args.turn,arm=="reminder",args.model,url,key)
              for arm in ("current","reminder")]
        for job in jobs:
            job.result()
