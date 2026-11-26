"""按公开题面复算 WorkBuddy 采购对账样例，并与随包参考答案逐集合比对。"""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import io
import json
import argparse
import tarfile

TASK = "wb-bench-office-v1.0/tasks/procurement-reconcile-L3-015/"


def read_rows(workspace, name):
    data = workspace.extractfile("input/" + name).read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(data)))


def compare(path):
    with tarfile.open(path) as archive:
        gold = json.load(archive.extractfile(TASK + "tests/gold/gold_answer.json"))
        data = archive.extractfile(TASK + "environment/workspace.tar.gz").read()
    with tarfile.open(fileobj=io.BytesIO(data)) as workspace:
        orders = read_rows(workspace, "采购订单.csv")
        receipts = read_rows(workspace, "入库记录.csv")
    by_id = {row["ORDER_ID"]: row for row in orders}
    assert len(by_id) == len(orders)
    by_order = defaultdict(list)
    for row in receipts:
        order_id, _ = row["RECEIPT_NO"].rsplit("-", 1)
        by_order[order_id].append(row)
    quantity = set()
    amount = set()
    for key in by_id.keys() & by_order.keys():
        ordered = by_id[key]
        received = by_order[key]
        if Decimal(ordered["ORDER_QTY"]) != sum(Decimal(r["RECV_QTY"]) for r in received):
            quantity.add(key)
        if abs(Decimal(ordered["TOTAL_AMOUNT"]) - sum(Decimal(r["RECV_AMOUNT"]) for r in received)) > Decimal("0.01"):
            amount.add(key)
    missing = by_id.keys() - by_order.keys()
    orphans = {row["RECEIPT_NO"] for key in by_order.keys() - by_id.keys() for row in by_order[key]}
    gold_amount = {row["order_id"] for row in gold["amt_mismatches"]}
    return {
        "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "orders": len(orders), "receipts": len(receipts),
        "quantity": len(quantity), "amount": len(amount), "gold_amount": len(gold_amount),
        "overlap": len(quantity & amount), "missing": len(missing), "orphans": len(orphans),
        "quantity_ids_match": quantity == {row["order_id"] for row in gold["qty_mismatches"]},
        "amount_ids_match": amount == gold_amount,
        "amount_only_ids_match": amount - quantity == gold_amount,
        "missing_ids_match": missing == set(gold["unmatched_order_ids"]),
        "orphan_ids_match": orphans == set(gold["unmatched_receipt_nos"]),
        "excluded_amount_ids": sorted(amount - gold_amount),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Path to wb-bench-office-v1.0.tar.gz")
    archive_path = parser.parse_args().archive
    print(json.dumps(compare(archive_path), indent=2, ensure_ascii=False))
