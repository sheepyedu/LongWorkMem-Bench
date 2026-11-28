"""Host-only state for a single, append-only office session."""
import os
import shutil
import stat
import tempfile
from pathlib import Path

ROUNDS = range(1, 10)
MAX_FILE = 32 * 1024 * 1024


def prepare(run: Path) -> Path:
    run.mkdir(parents=True, exist_ok=False, mode=0o700)
    work = run / "work"
    for directory in ("input", "inbox", "out", "notes", "scratch"):
        (work / directory).mkdir(parents=True)
    for directory in ("snapshots", "mail", "trace"):
        (run / directory).mkdir()
    return work


def safe_file(root: Path, path: Path) -> None:
    root = root.absolute()
    relative = path.absolute().relative_to(root)
    current = root
    if current.is_symlink():
        raise ValueError("Invalid workspace path")
    for part in relative.parts:
        current = current / part
        if part in (".", "..") or current.is_symlink():
            raise ValueError("Links or traversal outside office folders are unsupported")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
        raise ValueError("Expected a regular office file of at most 32 MiB")


def freeze(run: Path, turn: int, *, rounds=ROUNDS) -> None:
    """Copy delivered files atomically, without following symlinks or special files."""
    source = run / "work/out"
    root = run / "snapshots"
    final = root / str(turn)
    if turn not in rounds or final.exists() or source.is_symlink():
        raise ValueError("Invalid or already frozen business turn")
    stage = Path(tempfile.mkdtemp(dir=root, prefix=".stage-"))
    omissions = []
    try:
        for directory, subdirs, names in os.walk(source, followlinks=False):
            base = Path(directory)
            for name in list(subdirs):
                if (base / name).is_symlink():
                    omissions.append(str((base / name).relative_to(source)))
                    subdirs.remove(name)
            for name in names:
                path = base / name
                try:
                    safe_file(source, path)
                except (OSError, ValueError):
                    omissions.append(str(path.relative_to(source)))
                    continue
                target = stage / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        if omissions:
            import json
            (run / "trace" / f"omissions-{turn}.json").write_text(json.dumps(omissions, ensure_ascii=False))
        stage.rename(final)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
