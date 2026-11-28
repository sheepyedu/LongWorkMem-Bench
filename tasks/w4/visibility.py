"""A new business day starts only when the mounted public inbox matches the host."""

import hashlib
import json
import time
import unicodedata

from .office import invoke

READ_TREE = """python3 - <<'PYCODE'
import hashlib,json,unicodedata
from pathlib import Path
def read(p):
    try: return hashlib.sha256(p.read_bytes()).hexdigest()
    except FileNotFoundError: return None
rows = sorted((unicodedata.normalize('NFC',p.as_posix()),read(p))
              for p in Path('inbox').rglob('*') if p.is_file())
print(hashlib.sha256(json.dumps(rows).encode()).hexdigest())
PYCODE"""


def await_inbox(run, t, image):
    work = run / "work"
    rows = sorted(
        (
            unicodedata.normalize("NFC", p.relative_to(work).as_posix()),
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in (work / "inbox").rglob("*")
        if p.is_file()
    )
    expected = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    # Directory listings and a previously cached direct open can diverge on VM shares.
    retired = [
        f"inbox/06-{d:02}/{f}"
        for d in (2, 7)
        if t > d
        for f in (
            "值班签发名册.csv",
            "夜班/当班签单.csv",
            "签发原件.csv",
            "续办券.csv",
            "历史保障签章表.csv",
        )
    ]
    check = (
        READ_TREE
        + "\npython3 - <<'PYCODE'\nfrom pathlib import Path\nretired="
        + repr(retired)
        + """
for name in retired:
    if Path(name).exists(): print('expired path still visible')
    try: Path(name).read_bytes()
    except FileNotFoundError: continue
    print('expired file still readable')
PYCODE"""
    )
    deadline = time.monotonic() + 60
    attempts = 0
    while True:
        attempts += 1
        res = invoke(run, t, image, "shell", {"command": check})
        if res["status"] == 0 and res["output"].strip() == expected:
            return {
                "turn": t,
                "files": len(rows),
                "sha256": expected,
                "probes": attempts,
            }
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"R{t} Docker public inbox differs from its staged state"
            )
        time.sleep(0.4)
