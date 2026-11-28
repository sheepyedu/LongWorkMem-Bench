"""Behavioural replay. Each entry has its own customer, expectation, observation and weight."""

import argparse
import json
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

from tasks.c2.evolution.grade import indexed
from tasks.c2.evolution.grade import probe as paging_probe
from tasks.c2.evolution.oracle import state
from tasks.c2.grade import read, shown
from tasks.c2.subscriber import decode

from . import oracle
from .probes import replay
from .scenario import CHANNELS, DAYS, SCORING_REVISION, VERSION, questions


class Scores:
    def __init__(self):
        self.items = {}

    def group(self, t, label, budget, observations):
        weight = Fraction(budget, len(observations))
        if weight > 1:
            raise ValueError("business slice too broad: " + label)
        for key, expected, actual in observations:
            name = f"{t:02}/{label}/{key}"
            if name in self.items:
                raise ValueError(name)
            ok = type(expected) == type(actual) and expected == actual
            self.items[name] = dict(
                turn=t,
                metric=label,
                expected=expected,
                observed=actual,
                weight=str(weight),
                passed=ok,
            )


def fields_by_key(rows, keys, fields):
    """An invalid field costs only its own atom; duplicate keys stay ambiguous."""
    columns = [indexed(rows, keys, [f]) for f in fields]
    return {
        k: [c[k][0] if c.get(k) is not None else "missing" for c in columns]
        for k in columns[0]
    }


def evidence(result, expected, fields):
    # Requiring the complete business key avoids awarding one client's row to another.
    found = fields_by_key(result, ["account", "code", "day"], fields)
    checks = []
    for (code, day), row in expected.items():
        acct = row["account"]
        values = found.get((acct, code, day))
        for i, f in enumerate(fields):
            checks.append(
                (
                    f"{acct}/{code}/{day}/{f}",
                    row[f],
                    values[i] if values is not None else "missing",
                )
            )
    scope = {(row["account"], row["code"], row["day"]) for row in expected.values()}
    checks.append((acct + "/scope", True, set(found) == scope))
    return checks


def actual_notices(logs, t, a):
    return [
        b
        for b in logs[a]
        if b["turn"] == t and (t, a, b["key"]) != (8, "C", "handover-C-Q29")
    ]


def sequence(batches):
    return [r for b in batches for r in b["rows"].values()]


def delta_cases(t, p):
    result = []
    for a in CHANNELS:
        row = oracle.rows(a, t)["Q29", DAYS[1]]
        uid = row["uid"]
        want = oracle.events(a, t)[uid]
        full = p.get(f"delta-{a}-False")
        gap = p.get(f"delta-{a}-True")
        result.extend(
            [
                (a + "/settled", {}, full),
                (a + "/missing", want, gap.get(uid) if isinstance(gap, dict) else None),
                (
                    a + "/only-required",
                    [uid],
                    sorted(gap) if isinstance(gap, dict) else None,
                ),
            ]
        )
    return result


def paging_observations(snapshot, image):
    p = paging_probe(snapshot, 1, image, {})
    days = []
    day = date(2026, 3, 6)
    while day <= date(2046, 2, 9):
        days.append(day.strftime("%Y%m%d"))
        day += timedelta(weeks=1)
    ids = sorted(
        ["legacy-west"] + [code + "-" + d for code in ("K17", "M42") for d in days]
    )
    paging = []
    for n in (0, 7, 2020, 2079):
        page = p.get("p" + str(n))
        page = page if isinstance(page, dict) else {}
        items = page.get("items")
        got = (
            [x.get("uid") for x in items]
            if isinstance(items, list) and all(isinstance(x, dict) for x in items)
            else None
        )
        paging.extend(
            [
                (str(n) + "/uids", ids[n : n + 7], got),
                (
                    str(n) + "/cursor",
                    n + 7 if n + 7 < len(ids) else None,
                    page.get("next", "missing"),
                ),
            ]
        )
    return paging


def grade(run, image=None):
    m = json.loads((run / "manifest.json").read_bytes())
    if (m.get("protocol"), m.get("scoring_revision"), m.get("status")) != (
        VERSION,
        SCORING_REVISION,
        "complete",
    ) or [r["turn"] for r in m["turns"]] != list(range(1, 11)):
        raise ValueError("expected a complete customer migration edition")
    image = image or m["image"]
    s = Scores()
    g = s.group
    logs = {
        t: json.loads((run / "receipts" / f"{t}.json").read_bytes())
        for t in range(1, 11)
    }

    def snap(t):
        return run / "snapshots" / str(t)

    paging = paging_observations(snap(1), image)
    g(1, "pages", 4, paging)
    for t, mode, fields, budget in [
        (2, "live", ["utc", "booking"], 8),
        (3, "live", ["uid", "booking"], 3),
        (3, "early", ["uid"], 4),
        (3, "late", ["uid"], 4),
        (7, "annex", ["utc"], 2),
        (9, "restart", ["uid", "utc"], 6),
    ]:
        p = replay(run, t, image, mode)
        items = []
        versions = (
            [6, 7] if mode == "annex" else [3, 6, 7] if mode == "restart" else [t]
        )
        for v in versions:
            for a in CHANNELS:
                expected = oracle.rows(
                    a,
                    v,
                    cohort={"early": "new", "late": "old"}.get(mode, "normal"),
                    fallback=["14:05", "15:10", "16:15", "11:35"]
                    if mode == "annex"
                    else None,
                )
                items.extend(
                    (f"v{v}/{k}", want, got)
                    for k, want, got in evidence(
                        p.get(f"view-{a}-{v}"), expected, fields
                    )
                )
        g(t, mode, budget, items)
        if mode == "annex":
            base = replay(run, 7, image, "signed")
            selected = []
            for a, v in (("D", 7), ("D", 6), ("C", 7), ("A", 7)):
                key = ("Q29", DAYS[1])
                old = oracle.rows(a, v)[key]["utc"]
                new = oracle.rows(a, v, fallback=["14:05", "15:10", "16:15", "11:35"])[
                    key
                ]["utc"]
                actual = [
                    fields_by_key(
                        world.get(f"view-{a}-{v}"), ["code", "day"], ["utc"]
                    ).get(key, ["missing"])[0]
                    for world in (base, p)
                ]
                selected.append((a + f"/v{v}", [old, new], actual))
            g(7, "annex-pair", 4, selected)
        if t == 3 and mode == "live":
            legacy = []
            for a in CHANNELS:
                rows = oracle.rows(a, 3)
                old = next(
                    r
                    for r in rows.values()
                    if r["day"] == DAYS[0] and r["uid"].startswith("invite-")
                )
                new = next(
                    r
                    for r in rows.values()
                    if r["day"] == DAYS[0] and not r["uid"].startswith("invite-")
                )
                migrated = fields_by_key(
                    p.get(f"view-{a}-3"), ["code", "day"], ["uid"]
                ).get((new["code"], new["day"])) == [new["uid"]]
                raw = p.get("legacy-" + a) or [None, ""]
                legacy.extend(
                    [
                        (a + "/booking", old["uid"], raw[0] if migrated else None),
                        (
                            a + "/invite",
                            True,
                            migrated
                            and shown(raw[1], old["utc"][:16].replace("T", " ")),
                        ),
                    ]
                )
            g(3, "legacy-client", 2, legacy)
        if mode == "restart":
            clean_delta = delta_cases(9, p)
            g(9, "repair-on-clean-state", 6, clean_delta)
    for t, budget in [(4, 7), (6, 10)]:
        content = []
        precision = []
        protected = []
        for a in CHANNELS:
            want = oracle.events(a, t)
            before = state(logs[t - 1][a], t - 1)
            sent = sequence(actual_notices(logs[t], t, a))
            final = state(logs[t][a], t)
            for key, r in oracle.rows(a, t).items():
                uid = r["uid"]
                active = t == 4 or key == ("Q29", DAYS[1])
                if active:
                    content.append((a + "/" + uid, want[uid], final.get(uid)))
                else:
                    protected.append((a + "/" + uid, want[uid], final.get(uid)))
                hits = [x for x in sent if x["uid"] == uid]
                wanted = int(before.get(uid) != want[uid])
                precision.append(
                    (
                        a + "/" + uid,
                        wanted,
                        len(hits) if final.get(uid) == want[uid] else "unfulfilled",
                    )
                )
            extra = sorted({r["uid"] for r in sent} - set(want))
            precision.append(
                (a + "/foreign", [], extra if sent or final == want else "no delivery")
            )
        g(t, "client-state", 4, content)
        g(t, "notices", 3 if t == 4 else 4, precision)
        if t == 6:
            g(t, "protected-invites", 2, protected)
    preview = read(snap(5), "out/preview.json", json.loads)
    items = []
    for a in CHANNELS:
        row = oracle.rows(a, 4)["N84", DAYS[1]]
        got = fields_by_key(
            preview, ["account", "code", "day", "asof"], ["uid", "local"]
        ).get((a, "N84", DAYS[1], 4))
        local = (
            datetime.fromisoformat(row["utc"])
            .astimezone(ZoneInfo("Europe/London"))
            .strftime("%Y-%m-%d %H:%M")
        )
        for i, (name, want) in enumerate([("uid", row["uid"]), ("local", local)]):
            items.append(
                (
                    a + "/" + name,
                    want,
                    got[i] if got and not actual_notices(logs[5], 5, a) else None,
                )
            )
    g(5, "support", 4, items)
    items = []
    for a in CHANNELS:
        before = state(logs[6][a], 6)
        want = oracle.events(a, 7)
        plan = read(snap(7), f"out/plan-{a}.ics", decode)
        quiet = not actual_notices(logs[7], 7, a)
        for uid, row in want.items():
            needed = before.get(uid) != row
            # An absent plan or unsolicited delivery cannot satisfy a no-change row.
            observed = (
                "missing" if not isinstance(plan, dict) or not quiet else plan.get(uid)
            )
            items.append((a + "/" + uid, row if needed else None, observed))
        items.append(
            (
                a + "/foreign",
                [],
                sorted(set(plan) - set(want))
                if isinstance(plan, dict) and quiet
                else None,
            )
        )
    g(7, "withdrawal-plan", 8, items)
    paired = delta_cases(8, replay(run, 8, image, "incident"))
    g(8, "incident-replay", 6, paired)
    for t in [8, 9]:
        items = []
        for a in CHANNELS:
            sent = actual_notices(logs[t], t, a)
            allrows = sequence(sent)
            want = oracle.events(a, t)
            before = state(logs[t - 1][a], t - 1)
            if t == 8 and a == "C":
                before.update(
                    state(
                        [
                            b
                            for b in logs[t][a]
                            if b["turn"] == 8 and b["key"] == "handover-C-Q29"
                        ],
                        8,
                    )
                )
            needed = {uid: r for uid, r in want.items() if before.get(uid) != r}
            if t == 8 and a in ("C", "D"):
                needed = {}
            # Credit abstention only with evidence of a functional decision on that endpoint.
            capable = any(
                k == a + "/missing" and expected == got
                for k, expected, got in (paired if t == 8 else clean_delta)
            )
            for uid, r in want.items():
                hits = [x for x in allrows if x["uid"] == uid]
                expected = [r] if uid in needed else []
                items.append(
                    (
                        a + "/" + uid,
                        expected,
                        hits
                        if hits or capable or allrows
                        else "no demonstrated action",
                    )
                )
            unexpected = sorted({r["uid"] for r in allrows} - set(want))
            items.append(
                (a + "/foreign", [], unexpected if capable or allrows else None)
            )
            if t == 9 and a == "D":
                uid = oracle.rows(a, 9)["Q29", DAYS[1]]["uid"]
                items.append(
                    (
                        a + "/retry-key",
                        True,
                        any(
                            b["key"] == "handover-D-Q29"
                            and b["rows"] == {uid: want[uid]}
                            for b in sent
                        )
                        if uid in needed
                        else capable and not sent,
                    )
                )
        g(t, "actual-recovery", 4, items)
    result = read(snap(10), "out/inquiry.json", json.loads)
    qs = questions()
    fields = ["uid", "due", "received", "pending"]
    keys = ["account", "code", "day", "asof"]
    answers = fields_by_key(result, keys, fields)
    items = []
    for q in qs:
        expected = oracle.history(q, logs[10])
        k = tuple(q[name] for name in keys)
        got = answers.get(k)
        for i, f in enumerate(fields):
            items.append(
                (
                    "/".join(map(str, k)) + "/" + f,
                    expected[f],
                    got[i]
                    if got is not None
                    and not actual_notices(logs[10], 10, q["account"])
                    else "missing",
                )
            )
    for a in CHANNELS:
        keys_for_customer = {tuple(q[k] for k in keys) for q in qs if q["account"] == a}
        items.append(
            (
                a + "/question-set",
                True,
                {k for k in answers if k[0] == a} == keys_for_customer
                and not (set(answers) - {tuple(q[k] for k in keys) for q in qs})
                and not actual_notices(logs[10], 10, a),
            )
        )
    g(10, "historical-file", 6, items)
    p = replay(run, 10, image, "history")
    items = []
    flips = []
    for changed in ("none", *CHANNELS):
        found = fields_by_key(p.get(changed), keys, fields)
        for a in CHANNELS:
            row = oracle.rows(a, 7)["Q29", DAYS[1]]
            got = found.get((a, "Q29", DAYS[1], 7))
            stamp = "2026-03-09T20:10:00Z" if a == changed else row["utc"]
            for i, (field, want) in enumerate(
                zip(fields, [row["uid"], row["utc"], stamp, a == changed])
            ):
                if changed == a and field in ("received", "pending"):
                    original = fields_by_key(p.get("none"), keys, fields).get(
                        (a, "Q29", DAYS[1], 7)
                    )
                    initial = row["utc"] if field == "received" else False
                    flips.append(
                        (
                            a + "/" + field,
                            [initial, want],
                            [original[i], got[i]]
                            if got and original and not actual_notices(logs[10], 10, a)
                            else None,
                        )
                    )
                items.append(
                    (
                        changed + "/" + a + "/" + field,
                        want,
                        got[i]
                        if got and not actual_notices(logs[10], 10, a)
                        else "missing",
                    )
                )
    g(10, "alternate-receipt", 4, items)
    g(10, "single-receipt-flip", 4, flips)
    possible = sum(Fraction(v["weight"]) for v in s.items.values())
    if possible != 100:
        raise ValueError(f"expected 100 points, got {possible}")
    return dict(
        version=SCORING_REVISION,
        total=round(
            float(sum(Fraction(v["weight"]) for v in s.items.values() if v["passed"])),
            6,
        ),
        items=s.items,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run", type=Path)
    p.add_argument("--image")
    args = p.parse_args()
    print(json.dumps(grade(args.run.resolve(), args.image), indent=2))
