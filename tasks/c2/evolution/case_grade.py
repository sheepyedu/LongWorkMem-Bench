"""C2 case-based calibration. Frozen business prompts and receipts remain authoritative."""

import argparse
from datetime import datetime
import json
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo
from tasks.c2.grade import LEGACY

from .grade import equal_rows, flatten, legacy_grade, indexed, probe
from .oracle import calendar, history, state
from .scenario import CHANNELS, DAYS, SCORING_REVISION, identities, specs


def delta_score(batches, wanted):
    """One useful notice per changed UID. Wrong, repeated and unrelated notices cost precision."""
    sent = [(k, r) for batch in batches for k, r in batch["rows"].items()]
    if not wanted and not sent:
        return 1.0
    final = dict(sent)
    matched = {k for k, r in final.items() if k in wanted and r == wanted[k]}
    return 2 * len(matched) / (len(wanted) + len(sent))


def cold_cases(snap, image, logs):
    day = DAYS[2]
    world = {}
    for target in ("A", "C"):
        withdrawal = dict(
            id="W-handover", target="V-57", channels=target, start=day, end=day
        )
        world[target] = probe(snap, 9, image, logs, withdrawal=withdrawal)
    # Only the scope changes. The target has to revert to its original wall clock,
    # the neighbour retains the moved event, and version 9 remains readable in both.
    for ch in ("A", "C"):
        previous = calendar(9, ch, [day])
        uid = identities()["N84"][ch] + "-" + day.replace("-", "")
        updated = {**previous, uid: calendar(2, ch, [day])[uid]}
        for component in ("effective", "historical"):
            target_checks = {}
            neighbour_fractions = []
            for scope, data in world.items():
                version = 10 if component == "effective" else 9
                want = updated if version == 10 and scope == ch else previous
                got = data.get(f"feed{ch}{version}")
                got = got if isinstance(got, dict) else {}
                target_checks[scope] = bool(
                    data.get("imported") and got.get(uid) == want[uid]
                )
                neighbour_fractions.append(
                    equal_rows(
                        {k: v for k, v in got.items() if k != uid},
                        {k: v for k, v in want.items() if k != uid},
                    )
                )
            if component == "historical":
                changed = world[ch].get("feed" + ch + "10")
                target_checks["update_applied"] = (
                    isinstance(changed, dict) and changed.get(uid) == updated[uid]
                )
            protected = mean(neighbour_fractions)
            fraction = float(all(target_checks.values())) * (0.75 + 0.25 * protected)
            yield (
                ch + "." + component,
                fraction,
                dict(target=target_checks, neighbours=protected),
            )


def receipt_cases(snap, image):
    qs = [dict(channel=c, code="Q29", day=DAYS[2], asof=7) for c in CHANNELS]
    expectations = {}
    results = {}
    keys = ["channel", "code", "day", "asof"]
    fields = ["due", "received", "pending"]
    for changed in ("none", *CHANNELS):
        logs = {c: [] for c in CHANNELS}
        for q in qs:
            c = q["channel"]
            uid = identities()["Q29"][c] + "-" + DAYS[2].replace("-", "")
            due = calendar(7, c, [DAYS[2]])[uid]
            stamp = "2026-03-16T20:05:00Z" if c == changed else due["utc"]
            logs[c] = [
                dict(
                    turn=6,
                    key="repair",
                    receipt=c + "-00001",
                    rows={uid: {**due, "utc": stamp}},
                )
            ]
        expectations[changed] = indexed(history(qs, logs), keys, fields)
        results[changed] = indexed(
            probe(snap, 10, image, logs, questions=qs).get("extra"), keys, fields
        )
    for c in CHANNELS:
        key = next(k for k in expectations[c] if k[0] == c)
        yield (
            c,
            dict(
                original=results["none"].get(key) == expectations["none"][key],
                changed=results[c].get(key) == expectations[c][key],
                neighbours=results[c] == expectations[c],
            ),
        )


def past_score(rows, ch, clarified):
    fields = ["code", "utc", "day"]
    want = indexed(flatten(9, ch, DAYS), ["uid"], fields)
    got = indexed(rows, ["uid"], fields)
    if not clarified:
        zones = {s["code"]: ZoneInfo(s["zone"]) for s in specs()}
        for key, (code, utc, day) in want.items():
            local_day = (
                datetime.fromisoformat(utc).astimezone(zones[code]).date().isoformat()
            )
            if got.get(key) == [code, utc, local_day]:
                got[key] = [code, utc, day]
    return equal_rows(got, want)


def grade(run, *, image=None):
    evidence = {}
    old = legacy_grade(run, image=image, observations=evidence)
    clarified = bool(
        json.loads((run / "manifest.json").read_bytes()).get("material_revision")
    )
    source = old["checks"]
    checks = {}

    def f(key):
        return source[key]["fraction"]

    def add(t, key, weight, fraction, **detail):
        if key in checks or not 0 <= fraction <= 1:
            raise ValueError(key)
        checks[key] = dict(
            turn=t,
            weight=weight,
            fraction=float(fraction),
            earned=weight * fraction,
            **detail,
        )

    def receipts(t):
        return json.loads((run / "receipts" / f"{t}.json").read_bytes())

    previous_events = indexed(evidence[1].get("old"), ["uid"], ["utc"])
    legacy_times = mean(
        previous_events.get((uid,)) == [stamp] for uid, stamp in LEGACY.items()
    )
    for key, v in source.items():
        if key.startswith("paging."):
            # Inherited compatibility has value only in the presence of the paging fix.
            add(
                1,
                key,
                1,
                v["fraction"] * (0.5 + 0.5 * mean([f("legacy.detail"), legacy_times])),
            )
    for k, w in [
        ("rules.live", 2),
        ("rules.unseen.2", 2),
        ("rules.unseen.3", 2),
        ("rules.unseen.4", 4),
    ]:
        add(2, k, w, f(k))
    for c in CHANNELS:
        add(3, "wire." + c, 0.5, mean([f("wire.http." + c), f("wire.ics." + c)]))
        add(4, "launch." + c, 0.75, f("launch." + c))
    upgrade = probe(
        run / "snapshots/3", 3, old["replay_image"], {}, predecessor=run / "snapshots/2"
    )
    for c in ("C", "B"):
        want = calendar(3, c, [DAYS[2]])
        if c == "C":
            row = want.pop("line-401-20260316")
            row = {**row, "uid": "line-991-20260316"}
            want[row["uid"]] = row
        works = bool(upgrade.get("imported")) * equal_rows(
            upgrade.get("feed" + c), want
        )
        bookings = upgrade.get("bookings", 0)
        events = upgrade.get("events", 0)
        protection = 2 * bookings if c == "C" else bookings + events
        add(
            3,
            "upgrade." + c,
            3,
            works * (1 + protection) / 3,
            functional=works,
            bookings_preserved=bookings,
            events_preserved=events,
        )
    for k in ("preview.file", "preview.new"):
        add(5, k, 1, f(k))
    for t in (6, 8):
        previous, logs = receipts(t - 1), receipts(t)
        for c in CHANNELS:
            want = calendar(t, c, DAYS)
            before = state(previous[c], t - 1)
            sent = [b for b in logs[c] if b["turn"] == t]
            if t == 8 and c == "C":
                # The receiver accepted this batch before the agent regained control.
                injected = [b for b in sent if b["key"] == "C-resume-08"]
                before.update(state(injected, t))
                sent = [b for b in sent if b["key"] != "C-resume-08"]
            delta = {k: r for k, r in want.items() if before.get(k) != r}
            delivery = delta_score(sent, delta)
            if t == 6:
                add(6, "override.changed." + c, 1, f("override.changed." + c))
                add(6, "override.feed." + c, 0.5, f("override.feed." + c))
                add(6, "override.delivery." + c, 1.75, delivery)
            else:
                replay = f("resume.replay." + c)
                add(8, "resume.replay." + c, 2, replay)
                if c == "D":
                    uid = identities()["Q29"][c] + "-" + DAYS[2].replace("-", "")
                    uses_key = any(
                        b["key"] == "D-resume-08" and b["rows"] == {uid: want[uid]}
                        for b in sent
                    )
                    delivery = mean([delivery, float(uses_key)])
                elif not delta:
                    # A quiet channel alone cannot establish the ability to resume.
                    delivery *= replay
                add(8, "resume.delivery." + c, 2, delivery)
    for c, w in zip(CHANNELS, (1, 3, 3, 3)):
        add(7, "rollback.plan." + c, w, f("rollback.plan." + c))
    logs = receipts(9)
    for c in CHANNELS:
        sent = f("quarter.send." + c)
        if c == "C":
            sent = mean([sent, f("quarter.new-client")])
        add(9, "quarter.release." + c, 0.5, sent)
        add(9, "quarter.restore." + c, 0.5, f("quarter.backup." + c))
        add(
            9,
            "quarter.past." + c,
            1,
            past_score(evidence[9].get("api" + c), c, clarified),
        )
    for key, fraction, pair in cold_cases(
        run / "snapshots/9", old["replay_image"], logs
    ):
        add(9, "restore." + key, 2, fraction, worlds=pair)
    for k in ("due", "received", "pending"):
        add(10, "history.file." + k, 4 / 3, f("history.file." + k))
        add(10, "history.new." + k, 2, f("history.new." + k))
    quiet = not any(
        b["turn"] == 10 for batches in receipts(10).values() for b in batches
    )
    for ch, pair in receipt_cases(run / "snapshots/10", old["replay_image"]):
        add(
            10,
            "history.pair." + ch,
            2,
            quiet
            and pair["original"]
            and pair["changed"]
            and (0.75 + 0.25 * pair["neighbours"]),
            worlds=pair,
        )
    if abs(sum(v["weight"] for v in checks.values()) - 100) > 1e-9:
        raise ValueError("unexpected weights")
    return dict(
        version=SCORING_REVISION,
        legacy_total=old["total"],
        replay_image=old["replay_image"],
        total=round(sum(v["earned"] for v in checks.values()), 4),
        checks=checks,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--image")
    args = parser.parse_args()
    print(json.dumps(grade(args.run.resolve(), image=args.image), indent=2))
