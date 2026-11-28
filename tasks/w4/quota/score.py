"""Atomic host rubric. W4_QUOTA_PRIVATE_A79. Each atom owns its evidence and points."""

import csv
import io
import json
import os
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import load_workbook

from tasks.w1.scoring_workbook import InvalidArtifact, inspect_package

from ..night_score import recalculate
from ..office import attachment, events
from . import settlement
from . import world as w
from .desk import BATCH, DAYS, DESK, parse, replay
from .promise_score import integer_matches, scorecard


def charter(k, day, known):
    obj, site, _, _, ceil, rank = w.INFO[k]
    options = [(0, 0, "章程", ceil, rank)]
    removed = {v for t, vs in w.WITHDRAW.items() if t <= min(day, known) for v in vs}
    for serial, issued, start, end, case, owner, kind, qty, priority in w.documents():
        if (
            case != k
            or issued > known
            or not start <= day <= end
            or serial in removed
            or kind != "正本"
        ):
            continue
        if owner == "代办" and not (
            known >= 6
            and obj[-1] == w.SCOPES[site]
            and 9 <= day <= (9 if site in ("东港", "北仓") else 11)
        ):
            continue
        options.append((start, serial, str(serial), qty, priority))
    return max(options)[2:]


def voucher(k, day, known, history, promise=False):
    source, base, cap, start, end = w.VOUCHERS[k]
    if not start <= day <= end or any(
        k in ks for t, ks in w.VOID.items() if t <= min(day, known)
    ):
        legacy = 0
    else:
        legacy = min(cap, max(0, base - history[source]["实占"]))
    return settlement.entitlement(k, day, known, history, legacy) if promise else legacy


def layout(state, caps, day, known, history, promise=False):
    refs = {k: charter(k, day, known) for k in w.IDS}
    refs = {
        k: (doc, base, extra, base + extra, rank - int(extra > 0))
        for k, (doc, base, rank) in refs.items()
        for extra in [voucher(k, day, known, history, promise)]
    }
    queue = sorted(w.IDS, key=lambda k: (refs[k][-1], k))
    free = {
        p: caps[p] - sum(state[k]["锁定"] for k in w.IDS if w.INFO[k][1] == p)
        for p in caps
    }
    demand = {k: max(0, refs[k][3] - state[k]["锁定"]) for k in queue}
    left = free.copy()
    target = {}
    for k in queue:
        p = w.INFO[k][1]
        qty = min(demand[k], max(0, left[p]))
        left[p] -= qty
        target[k] = qty + state[k]["锁定"]
    return refs, queue, free, demand, target


def route(k, explain):
    code = w.INFO[k][0].split("-")[0]
    return (
        code.lower()
        + (".review" if explain and code in w.ROUTES else ".service")
        + "@office.test"
    )


def rows_at(path, cols):
    if not path.is_file():
        return {}, ["缺交"]
    rows = {}
    issues = []
    try:
        reader = csv.reader(
            io.StringIO(path.read_text(encoding="utf-8-sig")), strict=True
        )
        header = [v.strip() for v in next(reader, [])]
        if header.count("案号") != 1:
            return {}, ["案号列不能唯一定位"]
        keys = {c: header.index(c) for c in cols if header.count(c) == 1}
        issues.extend("缺列或重复:" + c for c in cols if c not in keys)
        keycol = header.index("案号")
        for r in reader:
            if not any(x.strip() for x in r):
                continue
            if len(r) <= keycol:
                issues.append("缺案号")
                continue
            k = r[keycol].strip()
            if k in rows:
                rows[k] = {}
                issues.append("重复:" + k)
                continue
            rows[k] = {c: r[i].strip() for c, i in keys.items() if i < len(r)}
            if k not in w.IDS:
                issues.append("未知:" + k)
    except (UnicodeError, csv.Error) as exc:
        return {}, [str(exc)]
    return rows, issues


def calc_evidence(path, image, state, caps, day, known, history, promise=False):
    refs, queue, free, dem, target = layout(state, caps, day, known, history, promise)
    expected = {}
    got = {}
    files = {}
    probes = {}
    error = None
    for p in w.POOLS:
        expected[p, "可再分容量"] = free[p]
    # One seat past the first customer guarantees a partial allocation for the second.
    middle_capacity = (
        {
            site: 3 + w.IDS.index(next(k for k in queue if w.INFO[k][1] == site)) % 4
            for site in w.POOLS
        }
        if promise
        else {}
    )
    middle_remaining = middle_capacity.copy()
    for i, k in enumerate(queue):
        p = w.INFO[k][1]
        if promise:
            n = 2 + w.IDS.index(k) % 4
            issued = min(n, middle_remaining[p])
            middle_remaining[p] -= issued
            expected[k, "部分容量兑现"] = [issued, n - issued]
        a = target[k] - state[k]["锁定"]
        expected.update(
            {
                (k, "顺序"): i + 1,
                (k, "站"): p,
                (k, "净需求"): dem[k],
                (k, "加配"): a,
                (k, "候补"): dem[k] - a,
                (k, "增容响应"): True,
                (k, "停办响应"): True,
            }
        )
    try:
        inspect_package(path)
        book = load_workbook(path)
        try:
            cs = book["容量"] if "容量" in book else None
            qs = book["队列"] if "队列" in book else None
            # Row and station keys are scored locally, including repeated case keys.
            csids = [cs.cell(i, 1).value for i in range(2, 6)] if cs is not None else []
            qids = [qs.cell(i, 1).value for i in range(2, 14)] if qs is not None else []
            for i, p in enumerate(csids, 2):
                if p in w.POOLS and csids.count(p) == 1:
                    got[p, "可再分容量"] = cs.cell(i, 2).value
            for i, k in enumerate(qids, 2):
                if k not in w.IDS or qids.count(k) != 1:
                    continue
                got[k, "顺序"] = i - 1
                got[k, "站"] = qs.cell(i, 2).value
                got[k, "净需求"] = qs.cell(i, 3).value
            if qs is None:
                return expected, got, "缺页:队列", {}
            files["baseline"] = path.read_bytes()
            # Edit a copy for each pair of stations; other stations remain untouched.
            # Two opposite edits force each row to demonstrate a real response.
            for poolset in (0, 1) if cs is not None else ():
                for mode in ("high", "low", "middle") if promise else ("high", "low"):
                    for i, p in enumerate(csids, 2):
                        cs.cell(i, 2).value = (
                            (
                                middle_capacity[p]
                                if mode == "middle"
                                else 120
                                if mode == "high"
                                else 0
                            )
                            if p in w.POOLS[poolset * 2 : poolset * 2 + 2]
                            else got.get((p, "可再分容量"))
                        )
                    for i, k in enumerate(qids, 2):
                        if k in w.IDS:
                            qs.cell(i, 3).value = (
                                (2 + w.IDS.index(k) % 4)
                                if w.INFO[k][1]
                                in w.POOLS[poolset * 2 : poolset * 2 + 2]
                                else got.get((k, "净需求"))
                            )
                    buf = io.BytesIO()
                    book.save(buf)
                    files[mode + str(poolset)] = buf.getvalue()
        finally:
            book.close()
    except (
        InvalidArtifact,
        BadZipFile,
        ParseError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        EOFError,
        OverflowError,
    ) as exc:
        error = type(exc).__name__ + ": " + str(exc)[:100]
    except OSError as exc:
        if exc.errno is not None:
            raise
        error = str(exc)
    if files and error is None:
        raw = recalculate(files, image)
        probes = {
            "observed": raw,
            "row_keys": qids,
            "edits": "每站对独立置容量120或0；该站对逐案需求为2+案号零基序号%4，其余输入沿用原件。",
        }
        if promise:
            probes["middle_capacity"] = middle_capacity
            probes["edits"] += (
                " 另将该站对的容量设为第一顺位探针需求加一，按有效顺位核对部分满足。"
            )
        for i, k in enumerate(qids):
            if k not in w.IDS or qids.count(k) != 1:
                continue
            got[k, "加配"], got[k, "候补"] = raw["baseline"][i]
            if not csids:
                continue
            pair = w.POOLS.index(w.INFO[k][1]) // 2
            hi, lo = raw["high" + str(pair)][i], raw["low" + str(pair)][i]
            unaffected = [raw[m + str(1 - pair)][i] for m in ("low", "high")]
            stable = all(x == raw["baseline"][i] for x in unaffected)
            n = 2 + w.IDS.index(k) % 4
            got[k, "增容响应"] = stable and hi == [n, 0] and hi != lo
            got[k, "停办响应"] = stable and lo == [0, n] and hi != lo
            if promise:
                got[k, "部分容量兑现"] = (
                    raw["middle" + str(pair)][i]
                    if raw["middle" + str(1 - pair)][i] == raw["baseline"][i]
                    else None
                )
    if files and not csids and error is None:
        error = "缺页:容量"
    return expected, got, error, probes


def score(run):
    run = Path(run)
    if not (run / "mail").is_dir():
        raise ValueError("宿主邮箱证据缺失")
    meta = json.loads((run / "manifest.json").read_text())
    image = os.getenv("W4_CALC_IMAGE") or meta.get("image") or "longworkmem-release:1"
    promise = meta.get("release_revision") == "4.2"
    clarified = promise or meta.get("release_revision") == "4.1"
    days, receipts = replay(run, 12)
    mail = events(run, 12)
    atoms = []
    issues = {}
    calc_probes = {}

    def atom(t, k, f, wt, want, seen, source):
        if seen is not None and not isinstance(seen, (bool, int, float, str, list)):
            seen = str(seen)
        ok = seen is not None and str(want).strip() == str(seen).strip()
        if (
            isinstance(want, int)
            and not isinstance(want, bool)
            and isinstance(seen, (int, float))
            and not isinstance(seen, bool)
        ):
            ok = want == seen
        if promise and isinstance(want, int) and not isinstance(want, bool):
            ok = integer_matches(want, seen)
        atoms.append(
            dict(
                id=f"R{t:02}/{k}/{f}",
                turn=t,
                case=k,
                field=f,
                maximum=wt,
                earned=wt if ok else 0,
                expected=want,
                observed=seen,
                evidence=source,
            )
        )

    for t in range(1, 13):
        snap = run / "snapshots" / str(t)
        if not snap.is_dir():
            raise ValueError(f"缺轮末快照 R{t}")
        opening, end, caps, operations = days[t]
        refs, q, free, demand, targets = layout(
            opening, caps, t, t, days[3][1], promise
        )
        if t in w.FILES:
            name, cols = w.FILES[t]
            path = name + ".csv"
            table, errors = rows_at(snap / path, cols)
            if errors:
                issues[f"{t}/{path}"] = errors
            budget = {1: 2, 2: 5, 4: 5, 5: 2, 6: 2, 7: 4, 11: 6, 12: 4}[t]
            for k in w.IDS:
                obj, p, orig, lock, ceil, rank = w.INFO[k]
                goal = targets[k]
                if t == 1:
                    values = [orig, lock, ceil]
                if t == 2:
                    values = charter(k, 3, 2)
                if t == 4:
                    values = [
                        days[3][1][k]["实占"],
                        opening[k]["实占"],
                        opening[k]["版本"],
                    ]
                if t == 5:
                    values = [route(k, True), route(k, False)]
                if t == 6:
                    values = [w.SCOPES[p], 9 if p in ("东港", "北仓") else 11]
                if t == 7:
                    values = [
                        charter(k, 9, 7)[0],
                        charter(k, 10, 7)[0],
                        days[3][1][w.VOUCHERS[k][0]]["实占"],
                        voucher(k, 9, 7, days[3][1], promise),
                    ]
                if t == 11:
                    values = [
                        days[3][1][k]["实占"],
                        days[10][1][k]["实占"],
                        opening[k]["实占"],
                        goal,
                        "解释"
                        if goal != opening[k]["实占"]
                        else "维持"
                        if k in w.CHALLENGES
                        else "无",
                    ]
                if t == 12:
                    values = [end[k]["实占"], end[k]["版本"], end[k]["最后受理号"]]
                for col, v in zip(cols, values, strict=True):
                    atom(
                        t,
                        k,
                        col,
                        budget / (12 * len(cols)),
                        v,
                        table.get(k, {}).get(col),
                        f"snapshots/{t}/{path}",
                    )
        if t in DAYS:
            cols = w.DISPATCH
            table, errors = rows_at(snap / "调度.csv", cols)
            if errors:
                issues[f"{t}/调度.csv"] = errors
            budget = {3: 14, 9: 16, 10: 16, 11: 6}[t]
            for k in w.IDS:
                rec = table.get(k, {})
                a = end[k]
                goal = targets[k]
                ops = [o for o in operations if o["案号"] == k]
                for col, v in zip(
                    cols, [*refs[k], goal, a["实占"], a["最后受理号"]], strict=True
                ):
                    atom(
                        t,
                        k,
                        "调度-" + col,
                        budget * (0.6 / 12 / len(cols)),
                        v,
                        rec.get(col),
                        f"snapshots/{t}/调度.csv",
                    )
                witnessed = bool(ops) or bool(rec) and rec.get("目标") == str(goal)
                if promise:
                    witnessed = (
                        any(
                            o.get("状态") in ("受理", "部分受理") or "新实占" in o
                            for o in ops
                        )
                        or bool(rec)
                        and integer_matches(goal, rec.get("目标"))
                    )
                atom(
                    t,
                    k,
                    "柜面实际席位",
                    budget / 60,
                    goal,
                    a["实占"] if witnessed else None,
                    "柜面轮末台账",
                )
                valid = [
                    o
                    for o in ops
                    if o.get("状态") in ("受理", "部分受理") and not o.get("重复")
                ]
                disciplined = all(
                    int(o["目标席"]) == goal and o["前值"] != o["实占"] for o in valid
                ) and (
                    opening[k]["实占"] == goal
                    or bool(valid)
                    or any(o.get("新实占") == goal for o in ops)
                )
                atom(
                    t,
                    k,
                    "授权动作范围",
                    budget / 60,
                    True,
                    disciplined if witnessed else None,
                    "柜面逐行回单",
                )
        if t == 11:
            for k in w.IDS:
                diff = targets[k] != opening[k]["实占"]
                needed = diff or k in w.CHALLENGES
                sent = [e for e in mail if e["subject"] == k and e["recipient"] != DESK]
                e = sent[0] if sent else None
                notice = w.FILES[11][0] + ".csv"
                declared, _ = rows_at(snap / notice, w.FILES[11][1])
                witnessed = bool(e) or declared.get(k, {}).get("通知") == "无"
                # No-contact cases only earn credit when explicitly and correctly closed.
                if not needed:
                    atom(
                        t,
                        k,
                        "维持安静",
                        7 / 12,
                        0,
                        len(sent) if witnessed else None,
                        "全程客户邮箱",
                    )
                    continue
                where = "全程客户邮箱"
                weight = 7 / 72
                atom(t, k, "送达次数", weight, 1, len(sent), where)
                atom(
                    t,
                    k,
                    "通知时点",
                    weight / 2 if clarified else weight,
                    11,
                    e["turn"] if e else None,
                    where,
                )
                if clarified:
                    changed_at = [
                        b["sequence"]
                        for b in mail
                        if b["turn"] == 11
                        and b["recipient"] == DESK
                        and any(
                            row.get("案号") == k
                            and not row.get("重复")
                            and (
                                row.get("状态") in ("受理", "部分受理")
                                or "新实占" in row
                            )
                            for row in receipts[b["receipt"]]
                        )
                    ]
                    after = (
                        bool(e)
                        and e["turn"] == 11
                        and e["sequence"] > max(changed_at, default=0)
                    )
                    atom(t, k, "办后才通知", weight / 2, True, after, where)
                atom(
                    t,
                    k,
                    "真实收件人",
                    weight,
                    route(k, diff),
                    e["recipient"] if e else None,
                    where,
                )
                try:
                    payload = (
                        parse(
                            attachment(run, e),
                            ("案号", "十日实占", "今日目标", "办后实占"),
                        )
                        if e
                        else []
                    )
                except (csv.Error, ValueError):
                    payload = []
                values = (
                    payload[0][1:]
                    if len(payload) == 1 and payload[0][0] == k
                    else [None] * 3
                )
                for col, v, obs in zip(
                    ("原承诺", "新承诺", "实际兑现"),
                    (days[10][1][k]["实占"], targets[k], end[k]["实占"]),
                    values,
                ):
                    atom(t, k, col, weight, v, obs, e["receipt"] if e else where)
        if t == 12:
            # Cap damage from unassigned objects; local errors already have case atoms.
            desk_mail = [e for e in mail if e["recipient"] == DESK]
            new_objs = [
                e["receipt"]
                for e in mail
                if e["recipient"] != DESK and e["subject"] not in w.IDS
            ]
            invalid = [
                e["receipt"]
                for e in desk_mail
                if e["turn"] not in DAYS or e["subject"] != BATCH
            ]
            malformed = [
                e["receipt"]
                for e in desk_mail
                if e["turn"] in DAYS
                and e["subject"] == BATCH
                and any(
                    "案号" not in row or row["案号"] not in w.IDS
                    for row in receipts[e["receipt"]]
                )
            ]
            invalid_sheet = [
                str(day) + "/" + name + ".csv"
                for day, (name, cols) in w.FILES.items()
                if set(rows_at(run / "snapshots" / str(day) / (name + ".csv"), cols)[0])
                - set(w.IDS)
            ]
            for label, errors in [
                ("客户通知范围", new_objs),
                ("柜面窗口与主题", invalid),
                ("柜面批次可归案", malformed),
                ("交接清单范围", invalid_sheet),
            ]:
                atom(
                    t,
                    "全台",
                    label,
                    0.25,
                    [],
                    errors if desk_mail else None,
                    "完整邮箱与冻结清单",
                )
        if t in (8, 12):
            expected, observed, error, probes = calc_evidence(
                snap / "预约.xlsx",
                image,
                opening,
                caps,
                9 if t == 8 else 12,
                t,
                days[3][1],
                promise,
            )
            calc_probes[str(t)] = probes
            if error:
                issues[f"{t}/预约.xlsx"] = error
            budget = 7 if t == 8 else 3
            for (k, col), v in expected.items():
                atom(
                    t,
                    k,
                    "预约-" + col,
                    budget / len(expected),
                    v,
                    observed.get((k, col)),
                    f"snapshots/{t}/预约.xlsx + Calc",
                )
    assert abs(sum(a["maximum"] for a in atoms) - 100) < 1e-8
    assert len({a["id"] for a in atoms}) == len(atoms)
    extra = {}
    if promise:
        atoms, extra["fulfilment"] = scorecard(atoms)
    return dict(
        **extra,
        version="release-v4.2"
        if promise
        else "release-v4.1"
        if clarified
        else "release-v4",
        total=round(sum(a["earned"] for a in atoms), 4),
        rounds=[
            round(sum(a["earned"] for a in atoms if a["turn"] == t), 6)
            for t in range(1, 13)
        ],
        atoms=atoms,
        format_issues=issues,
        calc_probes=calc_probes,
        counterparty_receipts=receipts,
    )
