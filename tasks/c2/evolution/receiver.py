from tasks.c2 import subscriber
from tasks.c2.scenario import write
from .scenario import CHANNELS, identities, DAYS


def publish(run, t, channel, key, file):
    return subscriber.publish(run, t, channel, key, file, CHANNELS)


def online(run, t, ch):
    batches = subscriber.receipts(run, ch, CHANNELS)
    return [b for b in batches if t < 5 or b["turn"] >= 5]


def archive(run):
    index = {}
    for ch in CHANNELS:
        file = f"vault/{ch}-closing-04.json"
        write(run / "work/input" / file, subscriber.receipts(run, ch, CHANNELS))
        index[ch] = file
    write(run / "work/input/vault/index.json", index)


def fault(run):
    pending = []
    for ch in "CD":
        uid = identities()["Q29"][ch] + "-" + DAYS[2].replace("-", "")
        row = dict(uid=uid, utc=DAYS[2] + "T15:00:00Z", status="CONFIRMED")
        key = f"{ch}-resume-08"
        pending.append(dict(channel=ch, key=key, row=row, transport="timeout"))
        if ch == "C":
            subscriber.accept(run, 8, ch, key, {uid: row}, CHANNELS)
    write(run / "work/input/interruption.json", pending)
