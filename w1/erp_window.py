"""Hosted ERP batch windows. Mail stays available after a connection window closes."""
from functools import partial
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from . import office
from .runstate import ROUNDS


LIMITS = dict(zip(ROUNDS, (9, 8, 5, 5, 10, 6, 12, 8, 8), strict=True))


SHORT_SHIFT = dict(zip(ROUNDS, (4, 5, 3, 3, 5, 3, 6, 5, 5), strict=True))


def limits_for(level):
    return {5: LIMITS, 6: SHORT_SHIFT}[level]


def notice(turn, level=5):
    return (f" 本部本次远程ERP作业窗口可提交{limits_for(level)[turn]}批共享盘作业。一次shell调用占一批，"
            "同一批可以连续执行多条命令或任意批量脚本，建议合并取件、办理及核对。"
            "已执行但命令出错也占一批，回执会显示余量。草稿、投递与文字汇报单独办理。"
            "用尽本次作业批数请汇报实际完成情况，下一委托会开新窗口，工作盘保留。")


def windowed_shell(run: Path, turn: int, request_id, command: str, backend="docker", *, limits=LIMITS):
    if not isinstance(command, str) or not command or len(command) > 100_000:
        raise ValueError("Expected a shell command up to 100,000 characters")
    limit = limits[turn]
    key = (turn, json.dumps(request_id), hashlib.sha256(command.encode()).hexdigest())
    db = sqlite3.connect(run / "trace/erp-window.sqlite", timeout=30)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS jobs (turn INTEGER, request TEXT, digest TEXT, result TEXT, "
                   "PRIMARY KEY(turn, request, digest))")
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT result FROM jobs WHERE turn=? AND request=? AND digest=?", key).fetchone()
        used = db.execute("SELECT COUNT(*) FROM jobs WHERE turn=?", (turn,)).fetchone()[0]
        if prior:
            if prior[0] is None:
                return dict(status=75, output="本批已受理，回执尚未返回。", remaining_batches=limit-used)
            return json.loads(prior[0])
        if used >= limit:
            return dict(status=75, remaining_batches=0, window_closed=True,
                        output="本次ERP作业窗口已关闭。邮箱仍可办理，下一委托重新开放共享盘作业。")
        db.execute("INSERT INTO jobs(turn,request,digest) VALUES (?,?,?)", key)
        db.commit()
        try:
            result = office.shell(run / "work", command, backend)
        except (OSError, ValueError):
            db.execute("DELETE FROM jobs WHERE turn=? AND request=? AND digest=?", key)
            db.commit()
            raise
        result["remaining_batches"] = limit-used-1
        db.execute("UPDATE jobs SET result=? WHERE turn=? AND request=? AND digest=?",
                   (json.dumps(result, ensure_ascii=False), *key))
        db.commit()
        return result
    finally:
        db.close()


if __name__ == "__main__":
    from .office_protocol import serve
    run = Path(sys.argv[1])
    manifest = run / "manifest.json"
    level = json.loads(manifest.read_bytes())["level"] if manifest.exists() else 5
    serve(run, int(sys.argv[2]), sys.argv[3], partial(windowed_shell, limits=limits_for(level)))
