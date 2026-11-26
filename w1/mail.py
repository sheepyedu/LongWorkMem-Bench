"""Snapshot the actual outgoing attachment at draft/send time."""
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from .runstate import ROUNDS, safe_file


def act(run: Path, turn: int, action: str, recipient: str, attachment: str, subject: str) -> str:
    if turn not in ROUNDS or action not in {"draft", "deliver"}:
        raise ValueError("Unknown mail operation")
    if not all(isinstance(s, str) and 0 < len(s) <= 512 for s in (recipient, attachment, subject)):
        raise ValueError("One recipient, one attachment and a subject are required")
    import re
    if not re.fullmatch(r"[a-zA-Z0-9._+-]+@office\.test", recipient):
        raise ValueError("Use one internal @office.test mailbox")
    relative = Path(attachment)
    if relative.is_absolute() or not relative.parts or relative.parts[0] != "out" or ".." in relative.parts:
        raise ValueError("Attachment must be a file in out/")
    source = run / "work" / relative
    safe_file(run / "work/out", source)
    root = run / "mail" / str(turn)
    root.mkdir(parents=True, exist_ok=True)
    receipt = ("D-" if action == "draft" else "M-") + uuid.uuid4().hex[:16]
    event = dict(receipt=receipt, turn=turn, action=action, recipient=recipient,
                 attachment=relative.as_posix(), subject=subject)
    stage = Path(tempfile.mkdtemp(dir=root, prefix=".stage-"))
    try:
        shutil.copyfile(source, stage / "payload")
        (stage / "event.json").write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
        stage.rename(root / receipt)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return receipt
