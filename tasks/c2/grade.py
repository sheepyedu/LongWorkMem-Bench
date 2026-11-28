"""Offline host-only calendar-v1 acceptance checks. No scorer enters the live desk."""

from datetime import date, timedelta
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import secrets
import subprocess
import tempfile

from tasks.c1.runstate import freeze
from tasks.w1.runstate import safe_file
from .pilot import execute
from .scenario import write, SERIES
from .subscriber import decode, instant

MARCH = ["20260306", "20260313", "20260320", "20260327"]
APRIL = [(date(2026, 4, 3) + timedelta(weeks=i)).strftime("%Y%m%d") for i in range(13)]
LEGACY = {"legacy-east": "2026-03-05T23:30:00Z", "legacy-west": "2026-03-06T02:15:00Z"}


def expected(stage, ch, days=MARCH, codes=("K17", "M42")):
    out = {}
    for i, code in enumerate(codes):
        for d in days:
            day = date.fromisoformat(d)
            hour = 15 if i == 1 or d == "20260306" else 14
            minute = 0
            if stage >= 5:
                if i == 0 and d == "20260320":
                    day -= timedelta(days=1)
                if (
                    i == 1
                    and d in ("20260313", "20260320")
                    and not (stage >= 6 and ch == "B" and d == "20260320")
                ):
                    hour = 17
            if stage >= 7 and i == 1 and d == "20260327":
                hour, minute = 16, 30
            uid = code + "-" + d
            out[uid] = dict(
                uid=uid, utc=f"{day}T{hour:02}:{minute:02}:00Z", status="CONFIRMED"
            )
    return out


def read(root, name, fn):
    try:
        file = root / name
        safe_file(root, file)
        return fn(file.read_bytes())
    except (OSError, ValueError, UnicodeError, TypeError):
        return None


def api(rows):
    if not isinstance(rows, list):
        return {}
    try:
        out = {
            r["uid"]: dict(uid=r["uid"], utc=instant(r["utc"]), status=r["status"])
            for r in rows
        }
        return out if len(out) == len(rows) else {}
    except (KeyError, TypeError, ValueError, AttributeError):
        return {}


def ratio(got, want):
    if not isinstance(got, dict) or not want:
        return 0.0
    return sum(got.get(k) == v for k, v in want.items()) / len(set(got) | set(want))


def view(log):
    result = {}
    for b in log:
        result.update(b["rows"])
    return result


def changed(old, target):
    return {k: v for k, v in target.items() if old.get(k) != v}


def notices(log, t):
    return [row for b in log if b["turn"] == t for row in b["rows"].values()]


class Visible(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.hide = 0

    def handle_starttag(self, t, a):
        if t in ("style", "script"):
            self.hide += 1

    def handle_endtag(self, t):
        if t in ("style", "script"):
            self.hide = max(0, self.hide - 1)

    def handle_data(self, data):
        if not self.hide:
            self.text.append(data)


def shown(body, stamp):
    if not isinstance(body, str):
        return False
    p = Visible()
    p.feed(body)
    return stamp in " ".join(" ".join(p.text).split())


# This harness runs only on disposable frozen copies, after the session.
PROBE = Path(__file__).with_name("probe.py")


def probe(snap, t, image):
    with tempfile.TemporaryDirectory(
        dir=os.getenv("C2_TEST_ROOT") or snap.parents[2]
    ) as tmp:
        w = Path(tmp) / "desk"
        freeze(snap, w)
        if t == 8:
            shutil.rmtree(w / "input")
            (w / "input").mkdir()
            for folder in ("data", "notes", "scratch"):
                shutil.rmtree(w / folder)
                (w / folder).mkdir()
            try:
                safe_file(w / "out", w / "out/backup.sqlite")
                shutil.copyfile(w / "out/backup.sqlite", w / "data/portal.sqlite")
            except (FileNotFoundError, ValueError, OSError):
                return {}
            shutil.rmtree(w / "out")
            (w / "out").mkdir()
        if t == 2:
            write(
                w / "input/intake.json",
                [dict(s, code=c) for s, c in zip(SERIES, ("P83", "Q74"))],
            )
        if t == 7:
            job = json.loads((w / "input/incident.json").read_text())
            job["B"]["key"] = "relay-other"
            job["B"]["uid"] = "M42-20260410"
            job["B"]["utc"] = "2026-04-10T16:30:00Z"
            write(w / "scratch/job.json", job)
            row = {k: v for k, v in job["B"].items() if k != "key"}
            prior = dict(
                key="april-B",
                receipt="B-00899",
                rows={row["uid"]: dict(row, utc="2026-04-10T15:00:00Z")},
            )
            write(w / "scratch/missing.json", [prior])
            write(
                w / "scratch/done.json",
                [
                    prior,
                    dict(key="relay-other", receipt="B-00900", rows={row["uid"]: row}),
                ],
            )
        tag = secrets.token_hex(16)
        (w / ("mount-" + tag)).write_text(tag)
        echo = w / "scratch" / ("mount-" + tag)
        result = execute(
            w,
            f"cp mount-{tag} scratch/mount-{tag} && python3 - {t} <<'PYPROBE'\n"
            + PROBE.read_text()
            + "\nPYPROBE",
            image,
        )
        if not echo.is_file() or echo.read_text() != tag:
            raise RuntimeError("Docker did not round-trip the frozen worktree mount")
        if result["status"] != 0:
            return {"fault": result["output"][-500:]}
        try:
            out = json.loads(result["output"])
        except ValueError:
            return {"fault": "invalid probe output"}
        for key in ("missing", "done", "export", "feedA", "feedB"):
            if out.get(key) is True:
                out[key] = read(w, "scratch/" + key + ".ics", decode)
        return out


def grade(run, *, image=None):
    meta = json.loads((run / "manifest.json").read_text())
    if meta["status"] != "complete" or len(meta["turns"]) != 8:
        raise ValueError("incomplete run")
    replay_image = (
        meta["image"]
        if image is None
        else subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
        ).strip()
    )
    checks = {}
    diagnostics = {}

    def add(key, w, frac):
        if not 0 <= frac <= 1:
            raise ValueError(key)
        checks[key] = dict(weight=w, fraction=float(frac), points=w * frac)

    state = {}
    for t in range(1, 9):
        snap = run / "snapshots" / str(t)
        if not snap.is_dir():
            raise ValueError(f"missing frozen snapshot {t}")
        log = json.loads((run / "receipts" / f"{t}.json").read_text())
        state[t] = log
        p = probe(snap, t, replay_image) if t in (1, 2, 4, 5, 6, 7, 8) else {}
        if "fault" in p:
            raise RuntimeError(f"probe transport failed in snapshot {t}: {p['fault']}")
        diagnostics[t] = {k: v for k, v in p.items() if k == "errors"}
        if t == 1:
            add("legacy.local-list", 3, shown(p.get("list"), "2026-03-06 08:30"))
            add("legacy.local-detail", 3, shown(p.get("detail"), "2026-03-05 21:15"))
            add(
                "legacy.utc",
                3,
                sum(
                    api(p.get("api")).get(k, {}).get("utc") == v
                    for k, v in LEGACY.items()
                )
                / 2,
            )
        if t == 2:
            rows = api(p.get("api"))
            imported = all(k + "-20260313" in rows for k in ("P83", "Q74"))
            add("migration.registrations", 3, imported and p.get("stable") is True)
            for ch, code in (("venue", "P83"), ("broadcast", "Q74")):
                want = {
                    k: v
                    for k, v in expected(2, "A", codes=("P83", "Q74")).items()
                    if k.startswith(code)
                }
                got = {k: v for k, v in api(p.get("api")).items() if k.startswith(code)}
                add("series." + ch, 7, ratio(got, want))
            add(
                "series.original-identity",
                4,
                sum(
                    all(k + d in rows for d in ("-20260306", "-20260313"))
                    for k in ("K17", "M42")
                )
                / 2,
            )
        if t == 3:
            vals = read(snap, "out/preview.json", json.loads)
            got = {}
            if isinstance(vals, list):
                for row in vals:
                    if isinstance(row, dict) and isinstance(row.get("uid"), str):
                        got[row["uid"]] = row.get("local")
            target = {
                k: v["utc"][:16].replace("T", " ") for k, v in expected(3, "A").items()
            }
            add(
                "preview.local",
                3,
                ratio(got, target)
                if isinstance(vals, list) and len(vals) == len(got)
                else 0,
            )
            add(
                "preview.no-send",
                1,
                not any(log.values())
                and any(target.get(k) == v for k, v in got.items() if k in target),
            )
        if t in (4, 5, 6, 7):
            for ch in ("A", "B"):
                curr = view(log[ch])
                prev = view(state[t - 1][ch])
                want = expected(t, ch)
                actual = notices(log[ch], t)
                if t == 4:
                    add("initial." + ch, 2, ratio(curr, want))
                    add("initial.feed." + ch, 2, ratio(p.get("feed" + ch), want))
                if t == 5:
                    for name, ids, w in [
                        ("moved", ["K17-20260320"], 2),
                        ("temporary", ["M42-20260313", "M42-20260320"], 2),
                        (
                            "neighbors",
                            sorted(
                                set(want)
                                - {"K17-20260320", "M42-20260313", "M42-20260320"}
                            ),
                            2,
                        ),
                    ]:
                        add(
                            name + "." + ch,
                            w,
                            sum(curr.get(k) == want[k] for k in ids) / len(ids),
                        )
                    add("update.feed." + ch, 1, ratio(p.get("feed" + ch), want))
                    add(
                        "delta." + ch,
                        1,
                        sorted(r["uid"] for r in actual) == sorted(changed(prev, want))
                        and curr == want,
                    )
                if t == 6:
                    add(
                        "withdraw." + ch,
                        3,
                        curr.get("M42-20260320") == want["M42-20260320"],
                    )
                    add(
                        "protected." + ch,
                        2,
                        sum(
                            curr.get(k) == v
                            for k, v in want.items()
                            if k != "M42-20260320"
                        )
                        / 7,
                    )
                    add("withdraw.feed." + ch, 1, ratio(p.get("feed" + ch), want))
                    add(
                        "scope." + ch,
                        1,
                        curr == want
                        and sorted(r["uid"] for r in actual)
                        == sorted(changed(prev, want)),
                    )
                if t == 7:
                    key = "urgent-0327-" + ch
                    uid = "M42-20260327"
                    # A committed before the outage. Its passive state alone gives
                    # no evidence of recovery: require correct replay on confirmed input.
                    recovered = ch == "B" or p.get("done") == {}
                    add(
                        "incident.received." + ch,
                        2,
                        recovered and curr.get(uid) == want[uid],
                    )
                    add(
                        "incident.once." + ch,
                        2,
                        recovered
                        and sum(r["uid"] == uid for r in actual) == 1
                        and any(
                            b["key"] == key and b["rows"].get(uid) == want[uid]
                            for b in log[ch]
                        ),
                    )
                    add(
                        "incident.unrelated." + ch,
                        1,
                        recovered
                        and not any(r["uid"] != uid for r in actual)
                        and curr.get(uid) == want[uid],
                    )
            if t == 7:
                add(
                    "recover.unsent",
                    3,
                    p.get("missing")
                    == {
                        "M42-20260410": dict(
                            uid="M42-20260410",
                            utc="2026-04-10T16:30:00Z",
                            status="CONFIRMED",
                        )
                    },
                )
                add("recover.confirmed", 3, p.get("done") == {})
        if t == 8:
            for ch in ("A", "B"):
                want = expected(8, ch, APRIL)
                sent = notices(log[ch], 8)
                exact = ratio({row["uid"]: row for row in sent}, want)
                add(
                    "quarter." + ch,
                    2,
                    exact * len({row["uid"] for row in sent}) / max(len(sent), 1),
                )
            want = expected(8, "A", APRIL)
            add(
                "fresh.subscription",
                2,
                ratio(read(snap, "out/new-A.ics", decode), want),
            )
            add("backup.export", 2, ratio(p.get("export"), want))
            add(
                "backup.legacy",
                2,
                shown(p.get("detail"), "2026-03-05 21:15")
                and p.get("bookings") is True,
            )
            both = api(p.get("api"))
            expected_old = expected(7, "B")
            add(
                "backup.policy",
                2,
                ratio({k: v for k, v in both.items() if k not in LEGACY}, expected_old),
            )
    assert sum(x["weight"] for x in checks.values()) == 100
    return dict(
        version="calendar-score/1.2",
        replay_image=replay_image,
        total=round(sum(x["points"] for x in checks.values()), 4),
        checks=checks,
        diagnostics=diagnostics,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument(
        "--image",
        help="Explicit rebuild on a machine without the original recorded Docker image",
    )
    args = parser.parse_args()
    print(json.dumps(grade(args.run.resolve(), image=args.image), indent=2))
