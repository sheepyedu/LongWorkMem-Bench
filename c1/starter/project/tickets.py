"""CSV 导入和出口命令。号码沿用旧设备登记表的整数类型。"""
import argparse
import csv
import sqlite3
from contextlib import closing


COLUMNS = ("number", "dept", "status")


def import_csv(db, path):
    db.execute("CREATE TABLE IF NOT EXISTS legacy "
               "(id INTEGER PRIMARY KEY, number INTEGER NOT NULL, dept TEXT NOT NULL, status TEXT NOT NULL)")
    with open(path, encoding="utf-8-sig", newline="") as stream, db:
        for row in csv.DictReader(stream):
            db.execute("INSERT INTO legacy(number,dept,status) VALUES(?,?,?)",
                       (int(row["number"]), row["dept"], row["status"]))


def export_csv(db, path):
    with open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows(db.execute("SELECT number,dept,status FROM legacy ORDER BY id"))


def main():
    parser = argparse.ArgumentParser(description="设备服务台 CSV 交换工具")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import-csv", "export-csv"):
        command = commands.add_parser(name)
        command.add_argument("db")
        command.add_argument("csv")
    args = parser.parse_args()
    with closing(sqlite3.connect(args.db)) as db:
        if args.command == "import-csv":
            import_csv(db, args.csv)
        else:
            export_csv(db, args.csv)


if __name__ == "__main__":
    main()
