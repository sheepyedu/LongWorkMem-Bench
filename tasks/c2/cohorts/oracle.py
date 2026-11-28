"""Host expectations for the signed, fixed public desk, independent of application code."""

from tasks.c2.evolution.oracle import state

from .scenario import CHANNELS, CODES, DAYS


def rows(account, version, *, cohort="normal", fallback=None):
    i = CHANNELS.index(account)
    result = {}
    for j, code in enumerate(CODES):
        old = ((i + j) % 2 == 0) if cohort == "normal" else cohort == "old"
        legacy = version < 3 or old
        old_id = f"invite-{account.lower()}-{31 + j}"
        new_id = ("n" if i < 2 else "s") + "-" + ("q" if j == 0 else "n")
        for day in DAYS:
            clock = (
                (fallback or ["14:05", "15:10", "16:15", "17:20"])[i]
                if j == 0
                else ("14:45" if day == DAYS[0] else "13:45")
            )
            if (
                j == 0
                and day == DAYS[1]
                and version >= 6
                and (account == "A" or version == 6)
            ):
                clock = "18:00"
            result[code, day] = dict(
                account=account,
                code=code,
                day=day,
                booking=f"BK-{821 + i * 2 + j}",
                uid=f"{old_id if legacy else new_id}-{day.replace('-', '')}",
                utc=f"{day}T{clock}:00Z",
            )
    return result


def events(account, version, **kwargs):
    return {
        r["uid"]: dict(uid=r["uid"], utc=r["utc"], status="CONFIRMED")
        for r in rows(account, version, **kwargs).values()
    }


def history(q, logs):
    a, v = q["account"], q["asof"]
    row = rows(a, v)[q["code"], q["day"]]
    got = state(logs[a], v).get(row["uid"], {}).get("utc")
    return dict(
        q, uid=row["uid"], due=row["utc"], received=got, pending=got != row["utc"]
    )
