"""Host-only offline walkthrough. Install each implementation in the reference run only."""
import argparse
import json
from pathlib import Path
import shlex

from c1 import runstate, sandbox, world


IMPLEMENTATION = Path(__file__).with_name("reference_solution")
CLI = "python3 project/tickets.py"
LIVE = "data/tickets.sqlite"


def python_command(source):
    return "python3 -c " + shlex.quote(source.strip())


CHECK_CSV = """
import csv
from pathlib import Path
def read(name):
    with Path(name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))
expected = read("input/legacy.csv")
for row in expected:
    row["number"] = str(int(row["number"]))
actual = read("scratch/roundtrip.csv")
assert actual == expected
print(actual)
"""

INSPECT_AUDIT = """
import sqlite3
with sqlite3.connect("data/tickets.sqlite") as conn:
    for decision, count in conn.execute("SELECT decision, count(*) FROM events GROUP BY decision ORDER BY decision"):
        print(decision, count)
    for row in conn.execute("SELECT event_id, decision FROM events WHERE decision IN ('conflict','corrected') ORDER BY event_id"):
        print(*row)
"""

CHECK_SAMPLE = """
import shutil, sqlite3, sys
from pathlib import Path
sys.path.insert(0, "project")
from tickets import apply_shard
target = shutil.copyfile("data/tickets.sqlite", "scratch/shard-test.sqlite")
with sqlite3.connect(target) as conn:
    path = Path("input/sample/trial.jsonl")
    apply_shard(conn, path)
    apply_shard(conn, path)
    assert conn.execute("SELECT count(*) FROM commits WHERE shard=?", (path.name,)).fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM events WHERE event_id='trial'").fetchone() == (1,)
print("Trial shard committed once across two deliveries")
"""

INSPECT_INTERRUPTION = """
import shutil, sqlite3
from pathlib import Path
copy = Path("scratch/incident")
shutil.copytree("data", copy)
with sqlite3.connect(copy / "tickets.sqlite") as conn:
    commits = conn.execute("SELECT shard FROM commits ORDER BY shard").fetchall()
    partial = conn.execute("SELECT count(*) FROM events WHERE event_id LIKE 's17-%'").fetchone()[0]
print("Committed shards:", len(commits), "last:", commits[-1], "shard 17 events:", partial)
"""

CHECK_REBUILD = """
import csv, json, sqlite3, subprocess, sys
from pathlib import Path
def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))
def snapshot(database):
    command = [sys.executable, "project/tickets.py"]
    values = [json.loads(subprocess.check_output([*command, "query", database, *flags]))
              for flags in ([], ["--through", "3"], ["--through", "4"])]
    with sqlite3.connect(database) as conn:
        values.append(conn.execute("SELECT event_id,decision FROM events ORDER BY event_id").fetchall())
        values.append(conn.execute("SELECT shard FROM commits ORDER BY shard").fetchall())
    current, history = (Path("scratch") / (Path(database).stem + suffix) for suffix in ("-now.csv", "-then.csv"))
    subprocess.run([*command, "report", database, current, history], check=True)
    return [*values, read_csv(current), read_csv(history)]
live = snapshot("data/tickets.sqlite")
rebuilt = snapshot("data/replayed.sqlite")
assert live == rebuilt
assert read_csv(Path("out/quarantine.csv")) == read_csv(Path("out/replay-quarantine.csv"))
print("Equal online/replay results for current, two queries, audit, commits, two reports and quarantine")
"""


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_reference(run, variant, *, alternate=False, backend="seatbelt"):
    run = Path(run)
    if variant not in {"A", "B"}:
        raise ValueError("variant must be A or B")
    run.mkdir(parents=True, exist_ok=True)
    if any(run.iterdir()):
        raise FileExistsError(f"The reference run directory must be empty: {run}")
    work = run / "work"
    world.initialize(work)
    trace = run / "trace"
    trace.mkdir()

    for turn in range(1, 13):
        request = world.release(work, turn, variant)
        log = {"turn": turn, "request": request, "commands": []}

        def execute(command, *, expected_status=0):
            result = sandbox.shell(work, command, backend=backend)
            log["commands"].append({"command": command, **result})
            save(trace / f"{turn:02}.json", log)
            if result["status"] != expected_status:
                raise RuntimeError(f"R{turn} {command} returned {result}")
            return result

        def write_module(name, source):
            execute(python_command(f"from pathlib import Path\nPath('project/{name}').write_text({source!r}, encoding='utf-8')"))

        def install(name, target=None):
            write_module(target or name, (IMPLEMENTATION / name).read_text(encoding="utf-8"))

        if turn == 1:
            execute(f"{CLI} import-csv scratch/legacy.sqlite input/legacy.csv")
            execute(f"{CLI} export-csv scratch/legacy.sqlite scratch/roundtrip.csv")
            execute(python_command(CHECK_CSV))
        elif turn == 2:
            execute("mv project/tickets.py project/legacy.py")
            install("tickets.py")
            install("migration.py")
            install("alternate_views.py" if alternate else "views.py", "views.py")
            execute(f"{CLI} migrate {LIVE} input/mapping.csv out/quarantine.csv")
            execute(f"{CLI} query {LIVE}")
        elif turn == 3:
            decision = (work / "input/decision.txt").read_text(encoding="utf-8")
            disposition = next(line for line in decision.splitlines() if line.startswith("本次处置："))
            if "允许按上述批准范围更正" in disposition:
                install("decision.py")
            else:
                write_module("decision.py", "def authorized(key, prior, proposed, approval):\n    return False\n")
            install("intake.py")
            execute(f"{CLI} ingest {LIVE} input/intake.jsonl")
        elif turn == 4:
            execute(f"{CLI} ingest {LIVE} input/late.jsonl")
            execute(f"{CLI} ingest {LIVE} input/late.jsonl")
            execute(f"{CLI} query {LIVE}")
            execute(python_command(INSPECT_AUDIT))
        elif turn == 5:
            install("shards.py")
            execute(python_command(CHECK_SAMPLE))
        elif turn == 6:
            command = world.batch_command(True)
            result = execute(command, expected_status=86)
            save(run / "fault.json", {"command": command, **result})
            runstate.freeze(work, run / "fault")
            execute(python_command(INSPECT_INTERRUPTION))
        elif turn == 7:
            install("failed_jobs.py")
            execute("python3 project/failed_jobs.py input/worker.log out/failed.txt")
        elif turn == 8:
            execute(world.batch_command(False))
        elif turn == 9:
            execute(f"{CLI} ingest {LIVE} input/amendments.jsonl")
            execute(python_command(INSPECT_AUDIT))
            execute(f"{CLI} query {LIVE}")
        elif turn == 10:
            execute(f"{CLI} ingest {LIVE} input/withdrawals.jsonl")
            execute(f"{CLI} query {LIVE} --through 3")
            execute(f"{CLI} query {LIVE} --through 4")
            execute(f"{CLI} query {LIVE}")
        elif turn == 11:
            install("reports.py")
            execute(f"{CLI} report {LIVE} out/current.csv out/history.csv")
        elif turn == 12:
            install("replay.py")
            execute(f"{CLI} replay input data/replayed.sqlite out/replay-quarantine.csv")
            execute(python_command(CHECK_REBUILD))
        save(trace / f"{turn:02}.json", log)
        runstate.freeze(work, run / "snapshots" / str(turn))
    return run


def main():
    parser = argparse.ArgumentParser(description="Generate a complete offline C1 reference run.")
    parser.add_argument("run", type=Path, help="new or empty reference run directory")
    parser.add_argument("--variant", choices=("A", "B"), required=True)
    parser.add_argument("--backend", choices=("seatbelt", "docker"), default="seatbelt")
    parser.add_argument("--alternate", action="store_true", help="use the independent Python read model")
    args = parser.parse_args()
    print(run_reference(args.run, args.variant, alternate=args.alternate, backend=args.backend))


if __name__ == "__main__":
    main()
