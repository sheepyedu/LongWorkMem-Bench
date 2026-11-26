"""Freeze a quiescent checkout without dereferencing participant-controlled links."""
import os
from pathlib import Path
import shutil
import stat
import tempfile


def freeze(source: Path, dest: Path) -> list[str]:
    source = source.resolve(strict=True)
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".freeze-"))
    omissions = []

    def copy_directory(folder, target):
        for item in sorted(folder.iterdir()):
            to = target / item.name
            info = item.lstat()
            if stat.S_ISDIR(info.st_mode):
                to.mkdir()
                copy_directory(item, to)
                shutil.copystat(item, to)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                shutil.copy2(item, to)
            elif stat.S_ISLNK(info.st_mode):
                link = os.readlink(item)
                try:
                    inside = not os.path.isabs(link) and item.resolve().is_relative_to(source)
                except (OSError, RuntimeError):
                    inside = False
                if inside:
                    to.symlink_to(link)
                else:
                    omissions.append(str(item.relative_to(source)))
            else:
                omissions.append(str(item.relative_to(source)))

    try:
        copy_directory(source, stage)
        stage.rename(dest)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return omissions
