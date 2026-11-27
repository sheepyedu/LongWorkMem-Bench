"""Experimental paired scoring of frozen artifacts, version granularity-1."""
from collections import Counter
import json
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from tasks.c1 import reserve, reserve_grade, settlement, settlement_grade as cg
from tasks.s1.circuit import Circuit, audit as audit_season
from tasks.s1.circuit_registration_audit import compare as compare_registration
from tasks.s1.relay import WEIGHTS
from tasks.w1 import advanced, advanced_memory as memory
from tasks.w1.scoring_tables import Table


def reserve_case(actual, expected):
    route = ("project", "desk", "authority")
    routed = memory.equal(actual, expected, route)
    decided = routed and memory.equal(actual, expected, ("decision", "target"))
    posted = decided and memory.equal(actual, expected, ("change",))
    return routed, decided, posted


def retained(snapshots, source, later, seed):
    keys = {(r["office"], r["case"]) for r in memory.cases(source, seed)}
    fields = memory.FIELDS.split(",")
    initial = Table(snapshots / str(source) / memory.form(source))
    before = memory.index(initial.rows)
    after = memory.index(Table(snapshots / str(later) / memory.form(source)).rows)
    return (set(initial.headers) == set(fields) and before.keys() == after.keys() == keys
            and all(len(before[k]) == len(after[k]) == 1
                    and memory.equal(after[k][0], before[k][0], fields) for k in keys))


def w1_score(run, manifest):
    original = advanced.grade(run, details=True)
    snapshots = run / "snapshots"
    seed = manifest["seed"]
    rules = memory.mandate(seed)
    effective = {"A": "2025-07-16", "B": "2025-08-16"}[manifest["variant"]]
    components = {}
    for turn in memory.DATES:
        previous = memory.filed_amounts(snapshots / "8" / memory.form(8)) if turn == 9 else {}
        expected = memory.posting(memory.cases(turn, seed), turn, rules, effective, previous)
        submitted = memory.index(Table(snapshots / str(turn) / memory.form(turn)).rows)
        keys = {(r["office"], r["case"]) for r in expected}
        n = len(keys | submitted.keys())
        hits = Counter()
        for row in expected:
            rows = submitted.get((row["office"], row["case"]), [])
            if len(rows) == 1:
                routed, decided, posted = reserve_case(rows[0], row)
                hits.update(route=int(routed), decision=int(decided), joint=int(posted))
        components[f"R{turn}"] = dict(old=4*hits["joint"]/n, new=(hits["route"]+hits["decision"]+2*hits["joint"])/n,
                                       checked=n, **hits)
    for source, mid in [(3,4),(5,6),(8,9)]:
        at_end = retained(snapshots, source, 9, seed)
        at_mid = retained(snapshots, source, mid, seed)
        components[f"retain.R{source}"] = dict(old=4*at_end/3, new=2*(at_end+at_mid)/3,
                                               intermediate_round=mid, intermediate=at_mid, final=at_end)
    old_points = sum(x["old"] for x in components.values())
    if abs(original["items"]["result.reserve"]["earned"] - old_points) >= 1e-5:
        raise ValueError("reconstructed strict reserve score differs from frozen score")
    total = original["total"] + sum(x["new"] for x in components.values()) - old_points
    return original["total"], total, components


def decision_fractions(submitted, expected, other):
    """Full table, all unique business IDs, and the subset affected by early authorization."""
    if not isinstance(submitted, list) or any(not isinstance(r, list) or len(r)!=2
            or not all(isinstance(v,str) for v in r) for r in submitted):
        return 0, 0, 0
    ids = Counter(r[0] for r in submitted)
    values = dict(submitted)
    correct = {k for k,v in expected.items() if ids[k] == 1 and values[k] == v}
    extras = values.keys() - expected.keys()
    changed = {k for k,v in expected.items() if other[k] != v}
    if not changed:
        raise ValueError("unusable counterfactual: no authorization-sensitive IDs")
    exact = correct == expected.keys() and not extras
    return int(exact), len(correct)/len(expected.keys() | extras), len(correct & changed)/(len(changed)+len(extras))


def decision_component(rows, expected, other, weight, old):
    strict, coverage, sensitive = decision_fractions(rows, expected, other)
    if abs(strict * weight - old) > 1e-8:
        raise ValueError("reconstructed strict decision score differs from frozen score")
    return dict(old=old, new=weight*(2*strict + coverage + sensitive)/4, weight=weight,
                exact=strict, row_fraction=coverage, sensitive_fraction=sensitive,
                sensitive_count=sum(expected[k] != other[k] for k in expected))


def decision_oracles(seed, variant):
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        for turn in range(1,6):
            settlement.release(base,turn,variant,seed,3)
        inp = base / "input"
        out = cg.ledger(inp, json.loads((inp/"jobs/corrections.json").read_text()))
    approvers = settlement.generate(seed,2,variant)[3]
    guarantee = reserve_grade.expected(seed,approvers["AB".index(variant)],reserve.requests(seed,*approvers,0))
    return {"corrections.audit":dict(out["audit"]), **{
        f"guarantee.{cut}.decisions":{k:v for day,k,v in guarantee["decisions"] if day==cut}
        for cut in reserve.CUTS}}


def c1_score(run, manifest):
    original = cg.grade(run, "docker")
    if not original["valid"] or not manifest.get("dispatch_window"):
        raise ValueError("expected a scorable historical dispatch run")
    arm = manifest["variant"]
    want = decision_oracles(manifest["seed"],arm)
    other = decision_oracles(manifest["seed"],"B" if arm=="A" else "A")
    components, totals = {}, {}
    for panel, folder in [("dispatch","dispatch"),("repaired","snapshots")]:
        checks = original[panel]["checks"]
        local = {}
        for turn, name, field in [(5,"corrections","audit"),(7,"guarantee","decisions")]:
            snap = cg.checkpoint_path(run,manifest,folder,turn)
            got = cg.load_output(snap,name)
            rows = got.get(field) if isinstance(got,dict) else None
            if name=="corrections":
                key = "corrections.audit"
                old,w = checks[key]
                local[key] = decision_component(rows,want[key],other[key],w,old)
            else:
                # Preserve the native grader's rejection of malformed/foreign cutoff rows.
                valid = isinstance(rows,list) and all(isinstance(r,list) and r and type(r[0]) is int
                                                      and r[0] in reserve.CUTS for r in rows)
                for cut in reserve.CUTS:
                    key = f"guarantee.{cut}.decisions"
                    actual = [r[1:] for r in rows if r[0]==cut] if valid else None
                    old,w = checks[key]
                    local[key] = decision_component(actual,want[key],other[key],w,old)
        totals[panel] = round(sum(v[0] for v in checks.values())+sum(x["new"]-x["old"] for x in local.values()),2)
        components[panel] = local
    components["panel_scores"] = totals
    return original["total"], round((2*totals["dispatch"]+totals["repaired"])/3,2), components


def pair_credit(actual, expected, stock=None):
    if actual is None:
        return 0
    if actual == expected:
        return 1
    return .25*sum(x == y and (stock is None or y != stock[i])
                   for i,(x,y) in enumerate(zip(actual,expected,strict=True)))


def order_components(grade, circuit=None):
    parts = {}
    for stage, weight in WEIGHTS.items():
        desk_scores = []
        for name, desk in grade["desks"].items():
            rows = [r for r in desk["rows"] if r["turn"]==stage]
            credits = []
            for r in rows:
                for i in (0,2):
                    actual = r["actual"]
                    stock = circuit.seasons[name].stock[r["team"]][i:i+2] if circuit else None
                    credits.append(pair_credit(actual[i:i+2] if actual is not None else None, r["expected"][i:i+2], stock))
            desk_scores.append(mean(credits)*.7*weight)
        parts[str(stage)] = dict(old=grade["groups"][str(stage)],new=mean(desk_scores))
    return parts


def s1_score(run, manifest):
    grade = audit_season(run)
    parts = order_components(grade)
    addition = sum(x["new"]-x["old"] for x in parts.values())
    circuit = Circuit(manifest["seed"], manifest["variant"], manifest["desks"], manifest["level"],
                      manifest["qualifiers"], version=manifest["score_version"])
    changed_only = order_components(grade, circuit)
    sensitive_gain = sum(x["new"]-x["old"] for x in changed_only.values())
    fmt = compare_registration(run)
    parts["changed_field_only"] = round(grade["total"] + sensitive_gain,3)
    parts["format_and_changed_field"] = round(fmt["alternative"] + sensitive_gain,3)
    parts["changed_field_stages"] = changed_only
    parts["format_only"] = fmt["alternative"]
    parts["both"] = round(grade["total"] + addition + fmt["alternative"]-fmt["official"],3)
    return grade["total"],round(grade["total"]+addition,3),parts
