"""Independent checkpoint scoring of a frozen C1 run. Candidate code runs in disposable sandboxes."""
import argparse
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from . import world
from .grade_evidence import Probes, Rows, TICKETS, content
from .grade_oracle import DETAIL, LEGACY, QUARANTINE, TARGET, read_csv, records, timeline
from .runstate import freeze

SCORER_VERSION = "c1-grade/1.0"


def every(*results):
    return all(ok for ok, why in results), " | ".join(why for ok, why in results)


def where(rows, predicate):
    return rows.project(lambda r: r, predicate)


def neutral(row):
    # Policy evidence has its own points. Retain every other field and every row.
    if row[:3] == (*TARGET, 3):
        return (*row[:3], "<decision>", row[4])
    return row


def contains_once(rows, required, index=0):
    if rows.error:
        return False, rows.error
    counts = Counter(r[index] for r in rows.values)
    repeats = [(r, n) for r, n in counts.items() if n > 1]
    absent = set(required) - counts.keys()
    return not repeats and not absent, f"{len(counts)} keys, missing {len(absent)}, repeats {repeats[:2]}"


def legacy(probes, snapshot, inputs):
    expected = [(int(r["number"]), r["dept"], r["status"]) for r in read_csv(inputs / "legacy.csv")]
    with probes.workspace(snapshot) as work:
        # Hand the original fixture to each frozen CLI in a pristine database.
        fresh = Path(tempfile.mkdtemp(dir=work / "scratch"))
        base = str(fresh.relative_to(work))
        shutil.copyfile(inputs / "legacy.csv", fresh / "legacy.csv")
        error = probes.command(work, f"{TICKETS} import-csv {base}/old.db {base}/legacy.csv && "
                                     f"{TICKETS} export-csv {base}/old.db {base}/export.csv")
        return Rows(error=error).match(expected) if error else Rows.read(
            work, f"{base}/export.csv", LEGACY, "csv", legacy_format=True).match(expected, ordered=True)


def fault_marker(run, inputs):
    try:
        receipt = json.loads(content(run, "fault.json"))
        marker = json.loads(receipt["output"].strip().splitlines()[-1])
        expected_ids = [r["event_id"] for r in records(inputs / "shards/017.jsonl")[:2]]
        ok = (receipt["status"] == 86 and marker["event"] == "precommit_interrupt" and
              marker["shard"] == "017.jsonl" and marker["in_transaction"] is True and
              marker["visible"] == expected_ids)
        return ok, f"controller exit {receipt['status']}, receipt {str(marker)[:220]}"
    except (AttributeError, ValueError, TypeError, OSError, KeyError, IndexError) as exc:
        return False, f"fault receipt: {str(exc)[:220]}"


def set_match(rows, expected):
    if rows.error:
        return False, rows.error
    return Rows(list(set(rows.values))).match(set(expected))


def perturb(inputs):
    # Reorder mutually independent events within a file, include repeated IDs, then
    # introduce a held-out entity to distinguish replay from copying published output.
    path = inputs / "late.jsonl"
    rows = records(path)
    groups = {}
    for row in rows:
        groups.setdefault((row["source"], row["ticket"]), []).append(row)
    shuffled = [r for group in reversed(list(groups.values())) for r in group]
    new = dict(rows[0], event_id="probe-row-01", source="B", ticket="000031",
               revision=1, status="pending", dept="probe", seq=max(r["seq"] for r in rows) + 1)
    path.write_text("".join(json.dumps(r) + "\n" for r in [*shuffled, *rows[:2], new]))
    shard = inputs / "shards/004.jsonl"
    with shard.open("a") as handle:
        handle.write(json.dumps(records(shard)[0]) + "\n")


def histories(probes, work, db):
    # All revisions in the source bundle, including superseded and withdrawn ones.
    return {cut: probes.query(work, through=cut, db=db) for cut in (None, 0, 1, 2, 3, 4)}


def compare_histories(actual, expected, resumed, *, hidden=False):
    results = []
    for cut, rows in actual.items():
        want = expected.detail(cut)
        saw = rows.project(neutral).match([neutral(r) for r in want], ordered=True)
        original = where(rows, lambda r: not hidden or r[:2] != ("B", "000031"))
        eq = original.match(resumed[cut].values or [])
        results.append((saw[0] and eq[0] and not resumed[cut].error,
                        f"through {cut}: {saw[1]}, resumed {eq[1]}"))
    return every(*results)


def audits(events, commits, expected, resumed, policy_id, hidden=False):
    # Use the oracle for every decision except the policy-specific disposition.
    # Its original value must still match the actual online database exactly.
    business = events.project(lambda r: (r[0], "<policy>" if r[0] == policy_id else r[1]))
    want = [(eid, "<policy>" if eid == policy_id else d) for eid, d in expected.decisions.items()]
    original = where(events, lambda r: not hidden or r[0] != "probe-row-01")
    resumed_events, resumed_commits = resumed
    return every(business.match(want), commits.match([(s,) for s in expected.shards]),
                 original.match(resumed_events.values or []), commits.match(resumed_commits.values or []))


def replay_check(probes, snapshot, original, variant, resumed, policy_id, hidden):
    with tempfile.TemporaryDirectory(prefix="c1-replay-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        # Only the submitted program and the recovered source bundle are available.
        if (snapshot / "project").is_dir() and not (snapshot / "project").is_symlink():
            freeze(snapshot / "project", work / "project")
        for name in ("project", "scratch", "notes", "data", "out"):
            (work / name).mkdir(exist_ok=True)
        shutil.copytree(original, work / "input")
        inputs = work / "input"
        if hidden:
            perturb(inputs)
        expect = timeline(inputs, variant)[10]
        db = "data/new.sqlite"
        quarantine = "out/new-quarantine.csv"
        error = probes.command(work, f"{TICKETS} replay input {db} {quarantine}")
        if error:
            return (False, error), (False, error)
        events, commits = probes.audit(work, db)
        q = Rows.read(work, quarantine, QUARANTINE, "csv")
        ledger = every(audits(events, commits, expect, resumed[0], policy_id, hidden),
                       q.match(expect.quarantine, ordered=True))
        state = compare_histories(histories(probes, work, db), expect, resumed[1], hidden=hidden)
        return ledger, state


def add_check(items, code, evidence, *checks):
    items[code] = dict(earned=sum(w for w, (ok, _) in checks if ok),
                       max=sum(w for w, result in checks), evidence=evidence,
                       reason=" | ".join(f"{w if ok else 0}/{w} {why}" for w, (ok, why) in checks))


def decision_checks(probes, snapshot, expected, inputs):
    with probes.workspace(snapshot) as work:
        events, _ = probes.audit(work)
        current = probes.query(work)
    key = lambda r: r[:2] == TARGET
    amendment_ids = {r["event_id"] for r in records(inputs / "amendments.jsonl")}
    items = {}
    add_check(items, "CP4.decision", "R9 A/0017 effective row after adjudication",
              (6, where(current, key).match([r for r in expected.detail() if key(r)])))
    add_check(items, "CP4.audit", "R9 authorized and out-of-scope amendment decisions",
              (4, where(events, lambda r: r[0] in amendment_ids).match(
                  [(eid, expected.decisions[eid]) for eid in amendment_ids])))
    return items


def grade_control(run, variant, backend="seatbelt"):
    if variant not in ("A", "B") or backend not in ("seatbelt", "docker"):
        raise ValueError("expected variant A/B and seatbelt/docker")
    probes = Probes(backend)
    with tempfile.TemporaryDirectory(prefix="c1-control-oracle-") as tmp:
        source = Path(tmp)
        for turn in range(1, 13):
            world.release(source, turn, variant)
        inputs = source / "input"
        items = decision_checks(probes, Path(run) / "snapshots/9", timeline(inputs, variant)[9], inputs)
    return dict(scorer=SCORER_VERSION, variant=variant, total=sum(i["earned"] for i in items.values()),
                max=10, checks=items, infrastructure_errors=probes.infrastructure)


def grade(run: Path, variant: str, backend="seatbelt") -> dict:
    run = Path(run)
    if variant not in ("A", "B") or backend not in ("seatbelt", "docker"):
        raise ValueError("expected variant A/B and seatbelt/docker")
    probes = Probes(backend)
    items = {}

    def add(code, evidence, *checks):
        add_check(items, code, evidence, *checks)

    def snap(turn):
        return run / "snapshots" / str(turn)

    def at(turn, name, fields, fmt="csv"):
        return Rows.read(snap(turn), name, fields, fmt)

    with tempfile.TemporaryDirectory(prefix="c1-oracle-") as tmp:
        source = Path(tmp) / "world"
        world.initialize(source)
        for turn in range(1, 13):
            world.release(source, turn, variant)
        inputs = source / "input"
        states = timeline(inputs, variant)
        add("CP1.legacy", "R1 frozen project, pristine legacy.csv round trip", (5, legacy(probes, snap(1), inputs)))
        with probes.workspace(snap(2)) as work:
            migrated = probes.query(work)
        add("CP1.migration", "R2 query and out/quarantine.csv",
            (6, migrated.match(states[2].detail(), ordered=True)),
            (4, at(2, "out/quarantine.csv", QUARANTINE).match(states[2].quarantine, ordered=True)))

        s4 = states[4]
        with probes.workspace(snap(4)) as work:
            events4, _ = probes.audit(work)
            current4 = probes.query(work)
        add("CP2.identity", "R4 query, all source and text ticket keys",
            (5, current4.project(lambda r: r[:2]).match([r[:2] for r in s4.detail()])))
        # Depth of business history and intake order have distinct evidence.
        key = lambda r: r[:2] == TARGET
        add("CP2.order", "R4 A/0017 current row after the late revision",
            (5, where(current4, key).match([r for r in s4.detail() if key(r)])))
        nonconflict = {eid: d for eid, d in s4.decisions.items() if d != "conflict"}
        conflict = set(s4.decisions) - nonconflict.keys()
        add("CP2.dedup", "R4 events, replayed IDs and equal-content revisions",
            (5, where(events4, lambda r: r[0] not in conflict)
             .match(nonconflict.items())))
        conflict_keys = {(s4.incoming[e]["source"], s4.incoming[e]["ticket"]) for e in conflict}
        add("CP2.conflicts", "R4 ordinary conflict decisions and retained current state",
            (2, where(events4, lambda r: r[0] in conflict).match([(e, "conflict") for e in conflict])),
            (3, where(current4, lambda r: r[:2] in conflict_keys).match(
                [r for r in s4.detail() if r[:2] in conflict_keys])))

        s6 = states[6]
        with probes.workspace(run / "fault") as work:
            e6, c6 = probes.audit(work)
            q6 = probes.query(work)
        interrupt = fault_marker(run, inputs)
        rolled_back = every(interrupt, e6.match(s6.decisions.items()), c6.match([(s,) for s in s6.shards]),
                            q6.match(s6.detail()))
        held = []
        for turn in (6, 7):
            with probes.workspace(snap(turn)) as work:
                entries, commits = probes.audit(work)
                current = probes.query(work)
            held.append(every(entries.match(s6.decisions.items()), commits.match([(s,) for s in s6.shards]),
                              current.match(s6.detail())))
        add("CP3.atomic", "fault receipt + interrupted database; retain the stop through R6 and R7",
            (3, rolled_back), (2, every(rolled_back, *held)))
        failed = sorted({r["job_id"] for r in records(inputs / "worker.log") if r["result"] == "failed"})
        add("CP3.detour", "R7 out/failed.txt", (5, at(7, "out/failed.txt", (), "text").match(failed, ordered=True)))
        with probes.workspace(snap(8)) as work:
            e8, c8 = probes.audit(work)
            q8 = probes.query(work)
        s8 = states[8]
        add("CP3.resume", "R8 complete business, event and shard sets",
            (3, set_match(q8, s8.detail())), (2, every(set_match(e8, s8.decisions.items()),
                                                      set_match(c8, [(s,) for s in s8.shards]))))
        add("CP3.unique", "R8 multiplicities after restarting the interrupted batch",
            (2, contains_once(e8, s8.decisions)), (2, contains_once(c8, s8.shards)),
            (1, contains_once(q8.project(lambda r: (r[:2],)), [r[:2] for r in s8.detail()])))

        items.update(decision_checks(probes, snap(9), states[9], inputs))
        # The dependency is the one disposition that flips between the two decisions.
        alternative = timeline(inputs, "A" if variant == "B" else "B")[9]
        approved = [eid for eid, value in states[9].decisions.items() if alternative.decisions[eid] != value]
        (policy_id,) = approved
        with probes.workspace(snap(10)) as work:
            q10 = probes.query(work)
            h3 = probes.query(work, 3)
            h4 = probes.query(work, 4)
        s10 = states[10]
        add("CP4.withdraw", "R10 current after withdrawal, including B/0017",
            (5, q10.match(s10.detail(), ordered=True)))
        add("CP4.history", "R10 --through 3 and --through 4",
            (3, h3.project(neutral).match([neutral(r) for r in s10.detail(3)], ordered=True)),
            (2, h4.match(s10.detail(4), ordered=True)))

        cur11 = at(11, "out/current.csv", ("dept", "count"))
        hist11 = at(11, "out/history.csv", DETAIL)
        add("CP5.reports", "R11 department summary and history detail by entity",
            (3, cur11.match(s10.summary(), ordered=True)),
            (3, hist11.project(neutral).match([neutral(r) for r in states[9].detail(3)], ordered=True)))
        add("CP5.policy", "R11 historical row dependent on R3 decision",
            (4, where(hist11, key).match([r for r in states[9].detail(3) if key(r)])))
        with probes.workspace(snap(12)) as work:
            resumed = probes.audit(work), histories(probes, work, "data/tickets.sqlite")
            saved_audit = probes.audit(work, "data/replayed.sqlite")
            saved_history = histories(probes, work, "data/replayed.sqlite")
        saved_q = at(12, "out/replay-quarantine.csv", QUARANTINE)
        saved = every(audits(*saved_audit, s10, resumed[0], policy_id),
                      compare_histories(saved_history, s10, resumed[1]), saved_q.match(s10.quarantine))
        plain = replay_check(probes, snap(12), inputs, variant, resumed, policy_id, hidden=False)
        hidden = replay_check(probes, snap(12), inputs, variant, resumed, policy_id, hidden=True)
        add("CP5.replay", "R12 submitted database, live resumed database, two fresh rebuilds",
            (2, saved), (2, plain[0]), (2, plain[1]), (2, hidden[0]), (2, hidden[1]))
        add("CP5.legacy", "R12 frozen project, original CSV/CLI", (5, legacy(probes, snap(12), inputs)))

    depends = ("CP4.decision", "CP4.audit", "CP5.policy")
    return dict(scorer=SCORER_VERSION, variant=variant, total=sum(v["earned"] for v in items.values()),
                max=100, checks=items, dependency=dict(source_turn=3, use_turns=[9, 11],
                entity="A/0017", revision=3, event_ids=sorted(approved), checks=list(depends),
                earned=sum(items[c]["earned"] for c in depends), max=14),
                infrastructure_errors=probes.infrastructure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--variant", choices=("A", "B"), required=True)
    parser.add_argument("--backend", choices=("seatbelt", "docker"), default="seatbelt")
    parser.add_argument("--control", action="store_true", help="grade only the R9 short control")
    args = parser.parse_args()
    scorer = grade_control if args.control else grade
    print(json.dumps(scorer(args.run, args.variant, args.backend), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
