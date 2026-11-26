"""服务台的分片作业入口。运行目录为工位根目录。"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing


def install_interrupt(connection, shard):
    first, second = "s17-01", "s17-02"

    def stop_at_second_write():
        visible = [row[0] for row in connection.execute(
            "SELECT event_id FROM events WHERE event_id IN (?,?) ORDER BY event_id", (first, second))]
        if visible != [first, second] or not connection.in_transaction:
            raise RuntimeError("未观察到指定写入位置的事务")
        record = {"event": "precommit_interrupt", "shard": shard.name,
                  "visible": visible, "in_transaction": True}
        print(json.dumps(record), flush=True)
        # Abrupt process loss inside the SQLite statement, before control returns to the importer.
        os._exit(86)

    connection.create_function("stop_at_second_write", 0, stop_at_second_write)
    connection.execute("CREATE TEMP TRIGGER maintenance_after_write AFTER INSERT ON main.events "
                       "WHEN NEW.event_id='s17-02' BEGIN SELECT stop_at_second_write(); END")


def main():
    parser = argparse.ArgumentParser(description="分片入库服务")
    parser.add_argument("--interrupt", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(Path("project").resolve()))
    from tickets import apply_shard

    with closing(sqlite3.connect("data/tickets.sqlite")) as db:
        paths = sorted(Path("input/shards").glob("*.jsonl"))
        if not paths:
            parser.error("本期分片尚未到件")
        for path in paths:
            if args.interrupt and path.name == "017.jsonl":
                install_interrupt(db, path)
            apply_shard(db, path)
            if db.in_transaction:
                raise RuntimeError(f"{path.name} 返回时仍有未提交的事务")
    if args.interrupt:
        raise RuntimeError("本次作业未观察到指定的写入现场")
    print(f"分片队列处理完毕，共 {len(paths)} 片。")


if __name__ == "__main__":
    main()
