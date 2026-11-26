"""Private independent business calculation from the controller's pristine public releases."""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
from tempfile import TemporaryDirectory
from pathlib import Path

from .scoring_tables import number, read_csv
from .world import release

LEDGER = "po line project ordered net invoiced_qty invoiced_amount qty_diff amount_diff flags"
PAY = "project employee hours bonus"
SUMMARY = "project period hours bonus"


def ledger(directory):
    def rows(filename):
        return read_csv(directory / filename)[1]

    receipts, invoices, orphans = {}, {}, set()
    orders = {(r["po"], r["line"]): r for r in rows("orders.csv")}
    duplicate_keys = set()
    for file in sorted(directory.glob("receipts_*.csv")):
        for r in read_csv(file)[1]:
            key = r["po"], r["line"]
            if r["event"] in receipts:
                duplicate_keys.add(key)
            receipts[r["event"]] = (key, number(r["qty"]))
            if key not in orders:
                orphans.add(("receipt", r["event"], *key))
    for file in sorted(directory.glob("invoices*.csv")):
        for r in read_csv(file)[1]:
            key = r["po"], r["line"]
            invoices[r["invoice_line"]] = key, number(r["qty"]), number(r["amount"])
            if key not in orders:
                orphans.add(("invoice", r["invoice_line"], *key))

    amounts, invoiced, net = Counter(), Counter(), Counter()
    for key, q in receipts.values():
        net[key] += q
    for key, q, a in invoices.values():
        invoiced[key] += q
        amounts[key] += a
    result = []
    for key, r in orders.items():
        q = net[key] - number(r["ordered"])
        a = amounts[key] - net[key] * number(r["unit_price"])
        result.append(dict(po=key[0], line=key[1], project=r["project"], ordered=r["ordered"],
                           net=net[key], invoiced_qty=invoiced[key], invoiced_amount=amounts[key],
                           qty_diff=q, amount_diff=a, flags=("Q" if q else "") + ("A" if a else "")))
    return result, [dict(zip(("source", "id", "po", "line"), o)) for o in sorted(orphans)], duplicate_keys


def allocate(hours, pool):
    """Apply the public cent-floor rule and assign the whole residual to one employee."""
    total = sum(hours.values())
    awards = {e: (pool * h / total).quantize(Decimal(".01"), rounding=ROUND_FLOOR)
              for e, h in hours.items()}
    winner = min(hours, key=lambda e: (-hours[e], e))
    awards[winner] += pool - sum(awards.values())
    return awards


def payments(hours, pools):
    result = []
    for p, pool in pools.items():
        team = {e: h for (project, e), h in hours.items() if project == p and h > 0}
        if team:
            for e, bonus in allocate(team, pool).items():
                result.append(dict(project=p, employee=e, hours=team[e], bonus=bonus))
    return result


def expected(variant):
    with TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        for turn in range(1, 8):
            release(workspace, turn, variant)
            if turn == 2:
                june, orphans, duplicate_keys = ledger(workspace / "input")
            if turn == 5:
                july, july_orphans, _ = ledger(workspace / "input")
        directory = workspace / "input"
        releases = read_csv(directory / "releases.csv")[1]
        pools = {r["project"]: number(r["pool"]) for r in releases
                 if r["status"] == "已放行"}
        hours = defaultdict(Decimal)
        for row in read_csv(directory / "hours.csv")[1]:
            p = row["project"]
            if row["employee"] == "E07" and p == "共享":
                p = "乙" if variant == "A" else "甲"
            if p in pools:
                hours[p, row["employee"]] += number(row["hours"])
    pay = payments(hours, pools)
    summaries = {p: [dict(project=p, period="2025-07", bonus=pool,
                          hours=sum(row["hours"] for row in pay if row["project"] == p))]
                 for p, pool in pools.items()}
    return dict(june=june, july=july, orphans=orphans, july_orphans=july_orphans,
                duplicate_keys=duplicate_keys, projects={r["project"] for r in releases}, pools=pools,
                hours=dict(hours), pay=pay, summaries=summaries)
