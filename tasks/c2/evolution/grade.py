"""Host-only evidence grading for persistent, versioned software evolution."""

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
from zoneinfo import ZoneInfo

from tasks.c1.runstate import freeze
from tasks.c2.pilot import execute
from tasks.c2.grade import read, shown
from tasks.c2.scenario import write
from tasks.c2.subscriber import decode, instant
from .scenario import (
    CHANNELS,
    DAYS,
    LATE,
    VERSION,
    specs,
    identities,
    queries,
    approval,
)
from .oracle import calendar, state, history


def equal_rows(actual, want):
    if not isinstance(actual, dict) or not want:
        return 0
    return sum(actual.get(k) == v for k, v in want.items()) / len(
        set(actual) | set(want)
    )


def indexed(rows, keys, fields):
    out = {}
    if not isinstance(rows, list):
        return {}
    for index, row in enumerate(rows):
        try:
            key = tuple(row[k] for k in keys)
            hash(key)
        except (KeyError, TypeError):
            # An unidentifiable extra row remains in the denominator.
            out[(None, index, None)] = None
            continue
        if key in out:
            out[key] = None
            continue
        try:
            vals = []
            for field in fields:
                value = row[field]
                if field in ("utc", "due", "received") and value is not None:
                    value = instant(value)
                if field == "pending" and type(value) is not bool:
                    raise ValueError("expected a JSON boolean")
                vals.append(value)
            out[key] = vals
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            out[key] = None
    return out


def flatten(t, c, days):
    events = calendar(t, c, days)
    return [
        dict(
            **events[identities()[s["code"]][c] + "-" + d.replace("-", "")],
            code=s["code"],
            day=d,
        )
        for s in specs()
        for d in days
    ]


def extra_questions():
    return [
        dict(channel=c, code=k, day=d, asof=t)
        for c in "DCBA"
        for k in ("N84", "J31", "Q29")
        for t, d in ((4, DAYS[1]), (6, DAYS[2]), (7, DAYS[3]), (9, DAYS[2]))
    ]


def alternate_log(logs):
    """A different valid delivery history for the same policies and identifiers."""
    changed = {c: list(batches) for c, batches in logs.items()}
    for c in CHANNELS:
        uid = identities()["J31"][c] + "-" + DAYS[2].replace("-", "")
        changed[c].append(
            dict(
                turn=6,
                key="support-replay",
                receipt=c + "-99997",
                rows={
                    uid: dict(uid=uid, utc=DAYS[2] + "T19:35:00Z", status="CONFIRMED")
                },
            )
        )
        changed[c].reverse()
    return changed


def probe(snap, t, image, logs):
    with tempfile.TemporaryDirectory(
        dir=os.getenv("C2_TEST_ROOT") or snap.parents[2]
    ) as tmp:
        work = Path(tmp) / "desk"
        freeze(snap, work)
        if t == 9:
            for folder in ("input", "data", "notes", "scratch"):
                shutil.rmtree(work / folder)
                (work / folder).mkdir()
            data = read(work, "out/backup.sqlite", lambda x: x)
            if not data:
                return {}
            (work / "data/portal.sqlite").write_bytes(data)
            shutil.rmtree(work / "out")
            (work / "out").mkdir()
        nonce = secrets.token_hex(12)
        scratch = f"scratch/replay-{nonce}"
        sc = work / scratch
        sc.mkdir()
        if t == 2:
            write(
                sc / "inbound/portfolio.json",
                [
                    dict(
                        code="L-99",
                        sid="alt",
                        zone="America/Chicago",
                        clock="22:15",
                        basis="wall",
                        weekday=0,
                    )
                ],
            )
            terms = [
                approval("beta", "L-99", "C", DAYS[0], DAYS[3], 2, "03:15"),
                approval("alpha", "L-99", "C", DAYS[0], DAYS[2], 2, "12:00"),
                dict(id="neg", target="beta", channels="C", start=DAYS[1], end=DAYS[2]),
            ]
            for i, (v, rows) in enumerate(
                [
                    (4, [terms[2]]),
                    (2, terms[:2]),
                    (3, [dict(terms[1], id="mid", rank=1)]),
                ]
            ):
                write(sc / f"inbound/orders/{i}.json", dict(version=v, rows=rows))
        if t in (5, 10):
            write(sc / "lookups.json", extra_questions())
            write(sc / "ledger.json", alternate_log(logs))
        if t == 5:
            write(
                sc / "lookups.json",
                [dict(channel=c, code="N84", day=DAYS[1], asof=4) for c in "DCBA"],
            )
        if t == 8:
            for c in CHANNELS:
                desired = calendar(8, c, DAYS)
                k = sorted(desired)[2]
                bad = {**desired[k], "utc": "2026-03-02T00:00:00Z"}
                accepted = [
                    dict(turn=4, key="prime", receipt=c + "-00001", rows=desired),
                    dict(turn=6, key="later", receipt=c + "-00002", rows={k: bad}),
                ]
                write(sc / (c + "gap-receipts.json"), accepted)
                write(
                    sc / (c + "done-receipts.json"),
                    accepted
                    + [
                        dict(
                            turn=8,
                            key="repair",
                            receipt=c + "-00003",
                            rows={k: desired[k]},
                        )
                    ],
                )
        (work / nonce).write_text(nonce)
        out = f"{scratch}/result.json"
        cmd = (
            f"cp {nonce} scratch/{nonce} && python3 - {t} {out} <<'ENDPROBE'\n"
            + Path(__file__).with_name("probe.py").read_text()
            + "\nENDPROBE"
        )
        result = execute(work, cmd, image, timeout=240)
        if (
            read(work, "scratch/" + nonce, bytes) != nonce.encode()
            or result["status"] != 0
        ):
            raise RuntimeError(
                f"probe infrastructure failed (turn {t}): {result['output'][-300:]}"
            )
        data = read(work, out, json.loads)
        if not isinstance(data, dict):
            raise RuntimeError("missing host probe output")
        for k, v in list(data.items()):
            if k == "extra" and v is True:
                data[k] = read(work, scratch + "/extra.json", json.loads)
            if (k.startswith("feed") or k.endswith(("gap", "done"))) and v is True:
                data[k] = read(work, scratch + "/" + k + ".ics", decode)
        return data


def grade(run, *, image=None):
    m = json.loads((run / "manifest.json").read_text())
    if (
        m.get("protocol") != VERSION
        or m["status"] != "complete"
        or [x["turn"] for x in m["turns"]] != list(range(1, 11))
    ):
        raise ValueError("incomplete evolution run")
    replay_image = (
        m["image"]
        if image is None
        else subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
        ).strip()
    )
    checks = {}

    def add(k, w, f):
        if k in checks or not 0 <= f <= 1:
            raise ValueError(k)
        checks[k] = dict(turn=t, weight=w, fraction=float(f), earned=w * f)

    before = {c: {} for c in CHANNELS}
    for t in range(1, 11):
        snap = run / "snapshots" / str(t)
        if not snap.is_dir():
            raise ValueError("missing frozen workspace")
        logs = json.loads((run / "receipts" / f"{t}.json").read_text())
        p = probe(snap, t, replay_image, logs) if t in (1, 2, 3, 5, 6, 8, 9, 10) else {}
        if t == 1:
            # March 6, 2026 to February 9, 2046 inclusive.
            start = date(2026, 3, 6)
            dates = []
            day = start
            while day <= date(2046, 2, 9):
                dates.append(day.strftime("%Y%m%d"))
                day += timedelta(weeks=1)
            ids = sorted(
                ["legacy-west"] + [c + "-" + d for c in ("K17", "M42") for d in dates]
            )
            for n in (0, 7, 2020, 2079):
                page = p.get("p" + str(n))
                ok = False
                if isinstance(page, dict) and isinstance(page.get("items"), list):
                    ok = (
                        all(isinstance(r, dict) for r in page["items"])
                        and [r.get("uid") for r in page["items"]] == ids[n : n + 7]
                        and page.get("next", "missing")
                        == (n + 7 if n + 7 < len(ids) else None)
                    )
                add("paging." + str(n), 1, ok)
            add("legacy.detail", 1, shown(p.get("legacy"), "2026-03-06 08:30"))
            add(
                "legacy.v1",
                1,
                ("legacy-east",) in indexed(p.get("old"), ["uid"], ["utc"]),
            )
        if t == 2:
            add(
                "rules.live",
                6,
                equal_rows(
                    indexed(p.get("base"), ["code", "day"], ["utc"]),
                    indexed(flatten(2, "B", DAYS), ["code", "day"], ["utc"]),
                ),
            )
            for v, w in [(2, 3), (3, 3), (4, 4)]:
                # With beta withdrawn only days 9 and 16 fall through to alpha.
                want = {
                    ("L-99", d): [
                        d
                        + ("T12:00:00Z" if v == 4 and d in DAYS[1:3] else "T03:15:00Z")
                    ]
                    for d in DAYS
                }
                got = indexed(p.get("new" + str(v)), ["code", "day"], ["utc"])
                add(
                    "rules.unseen." + str(v),
                    w,
                    equal_rows({k: x for k, x in got.items() if k[0] == "L-99"}, want)
                    if p.get("load")
                    else 0,
                )
        if t == 3:
            for c in CHANNELS:
                want = flatten(t, c, DAYS)
                add(
                    "wire.http." + c,
                    0.5,
                    equal_rows(
                        indexed(p.get("api" + c), ["code", "day"], ["uid", "utc"]),
                        indexed(want, ["code", "day"], ["uid", "utc"]),
                    ),
                )
                add(
                    "wire.ics." + c,
                    0.5,
                    equal_rows(p.get("feed" + c), calendar(t, c, DAYS)),
                )
        if t == 5:
            for key, vals, qs in [
                (
                    "preview.file",
                    read(snap, "out/preview.json", json.loads),
                    [
                        dict(channel=c, code="Q29", day=DAYS[2], asof=4)
                        for c in CHANNELS
                    ],
                ),
                (
                    "preview.new",
                    p.get("extra"),
                    [
                        dict(channel=c, code="N84", day=DAYS[1], asof=4)
                        for c in CHANNELS
                    ],
                ),
            ]:
                expected = []
                for q in qs:
                    r = next(
                        r
                        for r in flatten(4, q["channel"], [q["day"]])
                        if r["code"] == q["code"]
                    )
                    expected.append(
                        dict(
                            **q,
                            local=datetime.fromisoformat(r["utc"])
                            .astimezone(ZoneInfo("Europe/London"))
                            .strftime("%Y-%m-%d %H:%M"),
                        )
                    )
                score = equal_rows(
                    indexed(vals, list(qs[0]), ["local"]),
                    indexed(expected, list(qs[0]), ["local"]),
                )
                add(
                    key,
                    1,
                    score
                    if all(not any(b["turn"] == 5 for b in logs[c]) for c in CHANNELS)
                    else 0,
                )
        for c in CHANNELS:
            current = state(logs[c], t)
            this = [b for b in logs[c] if b["turn"] == t]
            sent = [k for b in this for k in b["rows"]]
            days = LATE if t == 9 else DAYS
            want = calendar(t, c, days)
            delta = {k: r for k, r in want.items() if before[c].get(k) != r}
            correct = equal_rows(current, want)
            if t == 4:
                add("launch." + c, 1.5, correct * len(set(sent)) / max(1, len(sent)))
            if t == 6:
                changed = {
                    k: r for k, r in want.items() if calendar(4, c, days)[k] != r
                }
                add(
                    "override.changed." + c,
                    1.5,
                    sum(current.get(k) == r for k, r in changed.items()) / len(changed),
                )
                add("override.feed." + c, 1, equal_rows(p.get("feed" + c), want))
                add(
                    "override.delta." + c,
                    1,
                    correct == 1 and sorted(sent) == sorted(delta),
                )
            if t == 7:
                plan = read(snap, "out/plan-" + c + ".ics", decode)
                frac = equal_rows(plan, delta) if delta else float(plan == {})
                add("rollback.plan." + c, 2, frac if not this and before[c] else 0)
            if t == 8:
                add("resume.state." + c, 1, correct)
                uid = identities()["Q29"][c] + "-" + DAYS[2].replace("-", "")
                original = c != "D" or any(
                    b["key"] == "D-resume-08" and b["rows"] == {uid: want[uid]}
                    for b in this
                )
                add(
                    "resume.side-effects." + c,
                    1,
                    original and correct == 1 and sorted(sent) == sorted(delta),
                )
                k = sorted(want)[2]
                add(
                    "resume.replay." + c,
                    1.5,
                    (
                        float(p.get(c + "done") == {})
                        + equal_rows(p.get(c + "gap"), {k: want[k]})
                    )
                    / 2,
                )
            if t == 9:
                actual = {k: r for b in this for k, r in b["rows"].items()}
                add(
                    "quarter.send." + c,
                    1,
                    equal_rows(actual, want) * len(set(sent)) / max(1, len(sent)),
                )
                add("quarter.backup." + c, 1, equal_rows(p.get("feed" + c), want))
                add(
                    "quarter.past." + c,
                    1,
                    equal_rows(
                        indexed(p.get("api" + c), ["code", "day"], ["uid", "utc"]),
                        indexed(flatten(9, c, DAYS), ["code", "day"], ["uid", "utc"]),
                    ),
                )
            before[c] = current
        if t == 9:
            add(
                "quarter.new-client",
                1,
                equal_rows(read(snap, "out/new-C.ics", decode), calendar(9, "C", LATE)),
            )
            add("quarter.invite", 1, shown(p.get("legacy"), "2026-03-06 08:30"))
        if t == 10:
            for label, qs, got, weight in [
                ("file", queries(), read(snap, "out/inquiry.json", json.loads), 10),
                ("new", extra_questions(), p.get("extra"), 6),
            ]:
                expected = history(qs, alternate_log(logs) if label == "new" else logs)
                for field in ("due", "received", "pending"):
                    keys = ["channel", "code", "day", "asof"]
                    frac = equal_rows(
                        indexed(got, keys, [field]), indexed(expected, keys, [field])
                    )
                    if any(b["turn"] == 10 for log in logs.values() for b in log):
                        frac = 0
                    add("history." + label + "." + field, weight / 3, frac)
    if abs(sum(x["weight"] for x in checks.values()) - 100) > 1e-8:
        raise ValueError("weights")
    return dict(
        version=VERSION + "/1.1",
        replay_image=replay_image,
        total=round(sum(x["earned"] for x in checks.values()), 4),
        checks=checks,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run", type=Path)
    p.add_argument("--image", help="locally rebuilt equivalent replay image")
    args = p.parse_args()
    print(json.dumps(grade(args.run.resolve(), image=args.image), indent=2))
