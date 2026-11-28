"""Verify replies against just the mail that had arrived before each original query."""

import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from ..office import invoke


def verify_replies(run, rounds):
    checks = []
    with TemporaryDirectory() as td:
        prefix = Path(td)
        (prefix / "mail").mkdir()
        shutil.copyfile(run / "manifest.json", prefix / "manifest.json")
        for row in rounds:
            turn = row["turn"]
            for n, act in enumerate(row["actions"], 1):
                name = act["tool"]
                if name in ("deliver", "draft") and not act["error"]:
                    rid = act["result"]["receipt"]
                    if not re.fullmatch(r"[MD]-[a-f0-9]{16}", rid):
                        raise ValueError("异常邮件回执")
                    rel = Path("mail") / str(turn) / rid
                    shutil.copytree(run / rel, prefix / rel)
                elif name == "receipt_query":
                    try:
                        got = invoke(prefix, turn, None, "receipt_query", act["args"])
                        match = not act["error"] and got == act["result"]
                    except ValueError as exc:
                        match = act["error"] and str(exc) == act["result"]
                    checks.append({"turn": turn, "operation": n, "matched": match})
    return checks
