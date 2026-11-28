"""Sensitivity check on this published run's audited 22 explanatory labels only."""

import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from tasks.w4.grade import grade
from tasks.w4.office import events

if __name__ == "__main__":
    source = Path(sys.argv[1])
    frozen = grade(source)
    edits = []
    with TemporaryDirectory() as td:
        dest = Path(td)
        shutil.copy(source / "manifest.json", dest)
        for part in ("mail", "snapshots"):
            shutil.copytree(source / part, dest / part)
        for e in events(dest, 12):
            p = dest / "mail" / str(e["turn"]) / e["receipt"] / "payload"
            raw = p.read_text()
            if "\n- 换机时限：" in raw:
                assert "\n## 说明\n" in raw and raw.count("\n- 换机时限：") == 1
                edits.append((e["turn"], e["subject"], e["receipt"]))
                p.write_text(raw.replace("\n- 换机时限：", "\n- 条款依据："))
        allow = set(
            json.loads(
                (Path(__file__).parent / "audited-note-receipts.json").read_text()
            )
        )
        assert {e[2] for e in edits} == allow
        assert len(edits) == len(allow) == 22
        result = grade(dest)
    print(
        json.dumps(
            {
                "official": frozen["total"],
                "sensitivity": result["total"],
                "rounds": result["rounds"],
                "daytime_points": result["daytime"]["total"] * 0.4,
                "delta": round(result["total"] - frozen["total"], 4),
            },
            indent=2,
        )
    )
