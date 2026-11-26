"""Author-side W1 walkthrough. Each action reads the business material released so far."""

import csv
import re
import shutil
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from functools import partial
from pathlib import Path

from openpyxl import Workbook


LEDGER = ("po", "line", "project", "ordered", "net", "invoiced_qty",
          "invoiced_amount", "qty_diff", "amount_diff", "flags")
BRIEF = ("po", "line", "flags", "qty_diff", "amount_diff")
PAY = ("project", "employee", "hours", "bonus")
PERIOD = "2025-07"
CENT = Decimal("0.01")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def reconcile(work, cutoff):
    inputs = work / "input"
    orders = read_csv(inputs / "orders.csv")
    order_keys = {(r["po"], r["line"]) for r in orders}
    net = Counter()
    invoiced = Counter()
    invoiced_amount = defaultdict(Decimal)
    orphans = []
    seen = set()

    def event_key(row, source, id_column):
        identity = (source, row[id_column])
        if identity in seen:
            return None
        seen.add(identity)
        key = (row["po"], row["line"])
        if key in order_keys:
            return key
        orphans.append(dict(source=source, id=row[id_column], po=key[0], line=key[1]))

    for path in sorted(inputs.glob("receipts_*.csv")):
        for row in read_csv(path):
            if date.fromisoformat(row["date"]) > cutoff:
                continue
            key = event_key(row, "receipt", "event")
            if key is not None:
                net[key] += int(row["qty"])
    for path in sorted(inputs.glob("invoices*.csv")):
        for row in read_csv(path):
            key = event_key(row, "invoice", "invoice_line")
            if key is not None:
                invoiced[key] += int(row["qty"])
                invoiced_amount[key] += Decimal(row["amount"])

    ledger = []
    for order in orders:
        key = (order["po"], order["line"])
        qty_diff = net[key] - int(order["ordered"])
        amount_diff = invoiced_amount[key] - net[key] * Decimal(order["unit_price"])
        flags = ("Q" if qty_diff else "") + ("A" if amount_diff else "")
        ledger.append(dict(order, net=net[key], invoiced_qty=invoiced[key],
                           invoiced_amount=invoiced_amount[key].quantize(CENT),
                           qty_diff=qty_diff, amount_diff=amount_diff.quantize(CENT), flags=flags))
    write_csv(work / "out/current.csv", LEDGER, ledger)
    write_csv(work / "out/orphans.csv", ("source", "id", "po", "line"), orphans)


def prepare_meeting(out):
    closed = read_csv(out / "frozen/2025-06.csv")
    exceptions = [row for row in closed if row["flags"]]
    write_csv(out / "brief.csv", BRIEF, exceptions)
    counts = {
        "total_lines": len(closed),
        "exception_lines": len(exceptions),
        "qty_lines": sum("Q" in row["flags"] for row in exceptions),
        "amount_lines": sum("A" in row["flags"] for row in exceptions),
        "orphan_events": len(read_csv(out / "orphans.csv")),
    }
    write_csv(out / "meeting.csv", counts.keys(), [counts])


def read_hours(work, projects):
    hr = (work / "inbox/HR-0628.eml").read_text(encoding="utf-8")
    employee = re.search(r"员工号：(\w+)", hr).group(1)
    source, target = re.search(r"共享支援工时由(\w+?)项目转归(\w+?)项目", hr).groups()
    effective = date.fromisoformat(re.search(r"批准生效日：(\d{4}-\d{2}-\d{2})", hr).group(1))
    policy = (work / "input/奖金分配办法.txt").read_text(encoding="utf-8")
    posted = date.fromisoformat(re.search(r"所有工时均发生在 (\d{4}-\d{2}-\d{2})", policy).group(1))
    shared_project = target if effective <= posted else source
    hours = defaultdict(Counter)
    for row in read_csv(work / "input/hours.csv"):
        project = row["project"]
        if (row["employee"], project) == (employee, "共享"):
            project = shared_project
        if project in projects:
            hours[project][row["employee"]] += Decimal(row["hours"])
    return hours


def allocate(pools, hours):
    pay = []
    for project, pool in pools.items():
        participants = {employee: h for employee, h in hours[project].items() if h > 0}
        total = sum(participants.values())
        if not participants:
            raise ValueError(f"Released project {project} has no approved hours")
        cents = int(pool * 100)
        base = {employee: int(cents * h / total) for employee, h in participants.items()}
        recipient = min(participants, key=lambda employee: (-participants[employee], employee))
        base[recipient] += cents - sum(base.values())
        for employee, h in sorted(participants.items()):
            pay.append(dict(project=project, employee=employee, hours=h,
                            bonus=(base[employee] * CENT).quantize(CENT)))
    return pay


def write_workbook(path, pools, pay):
    book = Workbook()
    budget = book.active
    budget.title = "Pools"
    budget.append(["project", "pool"])
    for project, pool in pools.items():
        budget.append([project, pool])
        budget.cell(budget.max_row, 2).number_format = "0.00"

    sheet = book.create_sheet("Pay")
    sheet.append([*PAY, "pool_cents", "total_hours", "floor_cents"])
    last = len(pay) + 1
    projects, staff, hours, base = (f"${col}$2:${col}${last}" for col in ("A", "B", "C", "G"))
    for r, row in enumerate(pay, 2):
        higher = f'COUNTIFS({projects},A{r},{hours},">"&C{r})'
        earlier_tie = f'COUNTIFS({projects},A{r},{hours},C{r},{staff},"<"&B{r})'
        remainder = f'E{r}-SUMIF({projects},A{r},{base})'
        sheet.append([
            row["project"], row["employee"], row["hours"],
            f'=IF(F{r}=0,0,(G{r}+IF(AND({higher}=0,{earlier_tie}=0),{remainder},0))/100)',
            f'=ROUND(SUMIF(Pools!$A$2:$A${budget.max_row},A{r},Pools!$B$2:$B${budget.max_row})*100,0)',
            f'=SUMIF({projects},A{r},{hours})',
            f'=IF(F{r}=0,0,INT(E{r}*C{r}/F{r}))',
        ])
        sheet.cell(r, 4).number_format = "0.00"
    book.save(path)


def prepare_pay(work):
    pools = {r["project"]: Decimal(r["pool"]) for r in read_csv(work / "out/released.csv")}
    pay = allocate(pools, read_hours(work, pools))
    write_csv(work / "out/pay.csv", PAY, pay)
    write_workbook(work / "out/bonus.xlsx", pools, pay)


def solve_turn(workspace: Path, turn: int, *, mail=None):
    """Complete one released request. The caller supplies the sandbox mailbox action."""
    work = Path(workspace)
    out = work / "out"
    if turn in (1, 2, 5):
        reconcile(work, date(2025, 7, 31) if turn == 5 else date(2025, 6, 30))
    elif turn == 3:
        freeze = out / "frozen/2025-06.csv"
        freeze.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / "current.csv", freeze)
    elif turn == 4:
        prepare_meeting(out)
    elif turn == 6:
        released = [row for row in read_csv(work / "input/releases.csv") if row["status"] == "已放行"]
        write_csv(out / "released.csv", ("project", "pool"), released)
    elif turn == 7:
        prepare_pay(work)
    elif turn in (8, 9):
        mail_turn(work, turn, mail)
    else:
        raise ValueError(f"Unknown W1 turn {turn}")


def mail_turn(work, turn, mail):
    if mail is None:
        raise ValueError("A sandbox mailbox action is required for draft and delivery")
    out = work / "out"
    pay = read_csv(out / "pay.csv")
    receipts = []
    for target in read_csv(work / "input/分发清册.csv"):
        recipient, attachment = target["recipient"], target["attachment"]
        scope = target["scope"].split("：")[0]
        subject = f"七月奖金材料（{scope}）"
        if turn == 8 and scope.endswith("项目负责人"):
            project = scope.removesuffix("项目负责人")
            rows = [r for r in pay if r["project"] == project]
            summary = dict(project=project, period=PERIOD, hours=sum(Decimal(r["hours"]) for r in rows),
                           bonus=sum(Decimal(r["bonus"]) for r in rows))
            write_csv(work / attachment, summary.keys(), [summary])
        receipt = mail("draft" if turn == 8 else "deliver", recipient, attachment, subject)
        receipts.append(dict(recipient=recipient, receipt=receipt, attachment=attachment))
    if turn == 9:
        write_csv(out / "receipts.csv", ("recipient", "receipt", "attachment"), receipts)


def run_reference(run: Path, variant: str):
    from w1 import mail, runstate, world

    work = runstate.prepare(run)
    for turn in range(1, 10):
        world.release(work, turn, variant)
        solve_turn(work, turn, mail=partial(mail.act, run, turn))
        runstate.freeze(run, turn)
