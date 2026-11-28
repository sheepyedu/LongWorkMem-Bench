"""Private calendar-evolution-v1 expectations, independent of the reference program."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from .scenario import batch, specs, identities


def calendar(t, ch, days, portfolio=None, orders=None):
    rules = (
        [(v, r) for v in (2, 6, 7, 9) for r in batch(v)] if orders is None else orders
    )
    out = {}
    for s in portfolio if portfolio is not None else specs():
        for d in days:
            scoped = [
                (v, r)
                for v, r in rules
                if v <= t and ch in r["channels"] and r["start"] <= d <= r["end"]
            ]
            revoked = {r["target"] for _, r in scoped if "target" in r}
            applicable = [
                (r["rank"], v, r["id"], r)
                for v, r in scoped
                if r.get("code") == s["code"] and r["id"] not in revoked
            ]
            policy = max(applicable)[-1] if applicable else s
            day = date.fromisoformat(d) + timedelta(days=policy.get("shift_days", 0))
            z = timezone.utc if policy["basis"] == "utc" else ZoneInfo(s["zone"])
            instant = datetime.combine(
                day, time.fromisoformat(policy["clock"]), z
            ).astimezone(timezone.utc)
            prefix = identities().get(s["code"], {}).get(ch, s["code"])
            uid = f"{prefix}-{d.replace('-', '')}"
            out[uid] = dict(
                uid=uid, utc=instant.strftime("%Y-%m-%dT%H:%M:%SZ"), status="CONFIRMED"
            )
    return out


def state(log, asof):
    current = {}
    for b in sorted(log, key=lambda item: (item["turn"], item["receipt"])):
        if b["turn"] <= asof:
            current.update(b["rows"])
    return current


def history(questions, logs):
    result = []
    for q in questions:
        c, d, t, code = (q[k] for k in ("channel", "day", "asof", "code"))
        uid = identities()[code][c] + "-" + d.replace("-", "")
        want = calendar(t, c, [d])[uid]["utc"]
        got = state(logs[c], t).get(uid, {}).get("utc")
        result.append(dict(**q, due=want, received=got, pending=got != want))
    return result
