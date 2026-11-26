"""服务台分片作业。运行目录为工位根目录。"""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys


def dispatch(before_shard=None):
    sys.path.insert(0, str(Path("project").resolve()))
    from tickets import apply_shard

    paths = sorted(Path("input/shards").glob("*.jsonl"))
    if not paths:
        raise ValueError("本期分片尚未到件")
    with closing(sqlite3.connect("data/tickets.sqlite")) as db:
        for path in paths:
            if before_shard is not None:
                before_shard(db, path)
            apply_shard(db, path)
            if db.in_transaction:
                raise RuntimeError(f"{path.name} 返回时仍有未提交的事务")
    print(f"分片队列处理完毕，共 {len(paths)} 片。")


if __name__ == "__main__":
    dispatch()
