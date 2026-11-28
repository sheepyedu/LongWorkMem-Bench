"""Independent host computation for the field-service appendix.

Allocation uses the ordered public registry and the participant's frozen dispatches.
Current-turn drafts or decisions are never used to compute today's required plan.
"""

from collections import Counter
import re
import unicodedata
from .annex import (
    CAPACITY,
    POOLS,
    REVISIONS,
    bases,
    documents,
    orders,
    signer,
    withdrawn,
)
from .office import attachment, status
from .scenario import FIRST, AUDITS

WEIGHTS = {2: 3, 3: 8, 4: 5, 6: 7, 9: 5, 10: 9, 11: 10, 12: 3}
FIELDS = ("服务主站", "服务凭证", "预留席位")


def fields(payload):
    text = unicodedata.normalize("NFKC", payload.decode("utf-8-sig", errors="replace"))
    out = []
    for key in FIELDS:
        values = re.findall(
            r"^[ \t]*(?:[-*][ \t]+)?" + key + r"[ \t]*:[ \t]*([^\n]*)$", text, re.M
        )
        out.append(values[0].strip() if len(values) == 1 else "无效")
    if not re.fullmatch(r"[0-9]{1,9}", out[2]):
        out[2] = "无效"
    else:
        out[2] = str(int(out[2]))
    return out


def station(obj, t):
    canceled = {serial for when, serial in withdrawn() if when <= t}
    valid = [
        (start, serial, site)
        for serial, o, b, start, end, site, who, kind in documents()
        if o == obj
        and b <= t
        and start <= t <= end
        and kind == "正式"
        and who == signer(o, b)
        and serial not in canceled
    ]
    return max(valid)[2] if valid else bases()[obj]


def capacity(t):
    result = Counter()
    for day, p, n in CAPACITY:
        if day <= t:
            result[p] += n
    return result


def debit(run, event, cut):
    p, _, n = fields(attachment(run, event))
    if (
        event["action"] == "deliver"
        and status(event, cut) != "退信"
        and p in POOLS
        and n != "无效"
    ):
        return p, int(n)
    return None, 0


def occupied(run, events, t, through):
    out = Counter()
    for e in events:
        if e["turn"] <= through:
            p, n = debit(run, e, t)
            if p:
                out[p] += n
    return out


def allocation(run, events, t, targets):
    actual = occupied(run, events, t, t - 1)
    remaining = {p: v - actual[p] for p, v in capacity(t).items()}
    resolved = {}
    meta = {}
    for k, priority, cat, device, rev, units, st in orders(t):
        meta[k] = (priority, cat)
        key = (k, device)
        if rev > resolved.get(key, (0, 0))[0]:
            resolved[key] = (rev, units if st == "有效" else 0)
    result = {}
    for k in sorted(targets, key=lambda k: (meta[k][0], k)):
        pool = station(targets[k][1], t)
        cat = meta[k][1]
        badge = f"S{POOLS.index(pool) + 1}{('驻场', '送修').index(cat) + 1}"
        for when, p, c, new in REVISIONS:
            if when <= t and (pool, cat) == (p, c):
                badge = new
        want = sum(n for (case, _), (_, n) in resolved.items() if case == k)
        issued = want if remaining[pool] >= want else 0
        remaining[pool] -= issued
        result[k] = [pool, badge, str(issued)]
    return result


def historical(run, events, plan):
    rows = {}
    for k in AUDITS:
        originals = [
            e
            for e in events
            if e["turn"] <= 3 and e["action"] == "deliver" and e["subject"] == k
        ]
        quantities = [fields(attachment(run, e))[2] for e in originals]
        rows[k] = dict(
            zip(
                ("原应签主站", "原应签凭证", "应配席位", "原实发席位", "截至4日实占"),
                [
                    *plan[k],
                    ";".join(sorted(quantities)) or "未发",
                    sum(debit(run, e, 4)[1] for e in originals),
                ],
            )
        )
    return rows
