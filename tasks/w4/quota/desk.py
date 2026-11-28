"""Deterministic booking counterparty. Replay immutable received batches in order."""

import csv
import io
import json
import re
import unicodedata
from copy import deepcopy

from .world import CAP, CAP_CHANGES, CASES, CO_SIGN, IDS, INFO, PENDING, PICKUPS, UNLOCK

DAYS = (3, 9, 10, 11)
DESK = "quota@office.test"
BATCH = "站务申请"
COLS = ("案号", "请求号", "预期版本", "目标席")


def parse(data, cols):
    if len(data) > 1_000_000:
        raise ValueError("文件过大")
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True)
    header = [c.strip() for c in next(reader, [])]
    if any(header.count(c) != 1 for c in cols):
        raise ValueError("表头缺失或重复")
    ix = [header.index(c) for c in cols]
    result = []
    for row in reader:
        if not any(x.strip() for x in row):
            continue
        if len(row) != len(header):
            raise ValueError("列数与表头不同")
        result.append([unicodedata.normalize("NFKC", row[i]).strip() for i in ix])
    return result


def replay(run, through):
    from ..office import attachment, events

    log = events(run, through)
    state = {
        k: {"实占": n, "锁定": f, "版本": 1, "最后受理号": "期初"}
        for k, _, _, n, f, _, _ in CASES
    }
    caps = CAP.copy()
    memo = {}
    receipts = {}
    days = {}
    for t in range(1, through + 1):
        for k, qty in PICKUPS.get(t, {}).items():
            v = state[k]
            v["实占"] = max(0, v["实占"] - qty)
            v["锁定"] = min(v["锁定"], v["实占"])
            v["版本"] += 1
        for k in UNLOCK.get(t, ()):
            state[k]["锁定"] = 0
            state[k]["版本"] += 1
        for p, n in CAP_CHANGES.get(t, {}).items():
            caps[p] += n
        opening = deepcopy(state)
        operations = []
        touched = set()
        settled = set()
        for e in (e for e in log if e["turn"] == t and e["recipient"] == DESK):
            ack = []
            receipts[e["receipt"]] = ack
            try:
                if e["subject"] != BATCH or t not in DAYS:
                    raise ValueError("窗口或主题不符")
                rows = parse(attachment(run, e), COLS)
                if not 1 <= len(rows) <= 12:
                    raise ValueError("一批1至12行")
            except (ValueError, csv.Error) as exc:
                ack.append({"状态": "退回", "原因": str(exc)})
                continue
            for i, (k, rid, rev, qty) in enumerate(rows, 1):
                op = {"案号": k, "请求号": rid, "预期版本": rev, "目标席": qty}
                operations.append(op)
                if (
                    k not in IDS
                    or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", rid)
                    or not all(re.fullmatch(r"[0-9]{1,8}", s) for s in (rev, qty))
                ):
                    ans = {"状态": "退回", "原因": "格式"}
                else:
                    identity = (k, int(rev), int(qty))
                    v = state[k]
                    p = INFO[k][1]
                    if rid in memo:
                        ident, first = memo[rid]
                        ans = (
                            {**first, "重复": True}
                            if ident == identity
                            else {"状态": "退回", "原因": "请求号冲突"}
                        )
                    elif int(rev) != v["版本"]:
                        ans = {
                            "状态": "退回",
                            "原因": "版本已变",
                            "当前版本": v["版本"],
                        }
                    elif (
                        k in PENDING.get(t, ())
                        and k not in settled
                        and int(qty) != v["实占"]
                    ):
                        settled.add(k)
                        v["实占"] = max(v["锁定"], v["实占"] - 1)
                        v["版本"] += 1
                        ans = {
                            "状态": "退回",
                            "原因": "承运回传",
                            "新实占": v["实占"],
                            "当前版本": v["版本"],
                        }
                    else:
                        before = v["实占"]
                        free = caps[p] - sum(
                            state[j]["实占"] for j in IDS if INFO[j][1] == p
                        )
                        applied = max(v["锁定"], min(int(qty), before + max(0, free)))
                        if (
                            k in CO_SIGN.get(t, ())
                            and k not in touched
                            and abs(applied - before) > 1
                        ):
                            applied = before + (1 if applied > before else -1)
                        if applied != before:
                            touched.add(k)
                        v.update(
                            实占=applied,
                            版本=v["版本"] + 1,
                            最后受理号=e["receipt"] + "/" + str(i),
                        )
                        ans = {
                            "状态": "受理" if applied == int(qty) else "部分受理",
                            **v,
                            "前值": before,
                        }
                    memo.setdefault(rid, (identity, ans.copy()))
                ack.append({**op, **ans})
                op.update(ans)
        days[t] = (opening, deepcopy(state), caps.copy(), operations)
    return days, receipts


def compact(rows):
    columns = list(dict.fromkeys(col for row in rows for col in row))
    return {"列": columns, "行": [[row.get(c) for c in columns] for row in rows]}


def query(run, t, args):
    raw = unicodedata.normalize("NFKC", args["as_of"]).strip()
    if raw and not re.fullmatch(r"(?:06-|6月)?\d{1,2}日?", raw):
        raise ValueError("日期应为六月日号")
    cut = int(re.search(r"(\d{1,2})日?$", raw)[1]) if raw else t
    if not 1 <= cut <= t:
        raise ValueError("只能查询已发生的业务日")
    days, receipts = replay(run, cut)
    opening, closing, cap, _ = days[cut]
    short = json.loads((run / "manifest.json").read_text()).get("release_revision") in (
        "4.1",
        "4.2",
    )
    if args["receipt"]:
        rows = receipts.get(args["receipt"], [])
        return compact(rows) if short else rows
    k = args["case"].strip()
    early = k == "开班" or k.startswith("开班/")
    if early:
        k = k.partition("/")[2]
    changes = short and k == "变动"
    if k and k not in IDS and not changes:
        raise ValueError("未知案号")
    selected = opening if early else closing
    rows = [
        {
            "案号": j,
            **(opening if early else closing)[j],
            "站": INFO[j][1],
            "本站容量": cap[INFO[j][1]],
        }
        for j in IDS
        if not k
        or j == k
        or (
            changes
            and (
                cut == 1
                or selected[j] != days[cut - 1][1][j]
                or cap[INFO[j][1]] != days[cut - 1][2][INFO[j][1]]
            )
        )
    ]
    return compact(rows) if short else rows
