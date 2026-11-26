"""Controller-only process-loss injection, executed inside a disposable code sandbox."""
import json
import os
import runpy


def install_interrupt(connection, shard):
    if shard.name != "017.jsonl":
        return
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


if __name__ == "__main__":
    runpy.run_path("input/batch.py")["dispatch"](install_interrupt)
    raise RuntimeError("本次作业未观察到指定的写入现场")
