"""Private W1 checkpoint scoring from frozen outputs and the host mail journal.

Version 1.4 checks the first submission and each employee input at both workbook deadlines.
Version 1.3 audits all actual deliveries and matches July receipts to the authorized R9 batch.
Version 1.2 accepts labeled totals, checks and explanatory footnotes in the workbook.
Version 1.1.1 observes the June 30 and July 8 warehouse posting cutoffs.
Version 1.1 adds pre-approval checks and tests the E07 dependency through actual pay.
Bonus drafts are distinguished from earlier unrelated drafts. Project-subject checks
require a concrete disclosure. Numeric grouping, OOXML sizes, and merge expansion
have explicit acceptance tests. The public fixture and stored trajectories are unchanged.
"""
import json
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from .scoring_mail import check_mail
from .scoring_oracle import LEDGER, PAY, allocate, expected
from .scoring_tables import InvalidArtifact, Table
from .scoring_workbook import check_workbook, same_workbook


SCORER_VERSION = "w1-grade/1.4"
# v1.3 SHA-256 over sorted repo-relative path + NUL + bytes + NUL for grade.py and scoring_*.py.
PREVIOUS_SCORER_SHA256 = "47493e46bf4bc0510d7d8edae269340889a59cf989854e460e91901f2fd3a9bc"


def preapproval(snapshots):
    for turn in range(1, 6):
        path = snapshots / str(turn) / "released.csv"
        if not path.exists():
            continue
        table = Table(path)
        if table.error:
            return False, f"R{turn} official release list unreadable"
        if any(r.get("project", "").strip() for r in table.rows):
            return False, f"R{turn} official release list contains a project before approval"
    return True, "no project listed as released before R6 written approval"


def key(r):
    return r["po"], r["line"]


def selected(table, expected_rows, fields, predicate):
    return table.matches(expected_rows, fields, predicate=predicate)


def flag_set(table, expected_rows, flag):
    try:
        rows = table.project(["po", "line", "flags"])
        if any(r["flags"] not in {"", "Q", "A", "QA"} for r in rows):
            raise InvalidArtifact("invalid exception flag")
        actual = sorted(key(r) for r in rows if flag in r["flags"])
        want = sorted(key(r) for r in expected_rows if flag in r["flags"])
        return actual == want, f"{flag} exception set: observed {actual}, expected {want}"
    except ValueError as exc:
        return False, str(exc)


def frozen_check(snapshots, oracle):
    closed = Table(snapshots / "3/frozen/2025-06.csv")
    keys_ok, why = closed.matches(oracle["june"], "po line")
    if not keys_ok:
        return False, f"June archive lacks a complete unique order-line set: {why}"
    try:
        rows = closed.project(LEDGER.split())
        if any(r["flags"] not in {"", "Q", "A", "QA"} for r in rows):
            raise InvalidArtifact("invalid frozen flags")
    except InvalidArtifact as exc:
        return False, str(exc)
    for turn in (2, 3):
        ok, why = Table(snapshots / str(turn) / "current.csv").matches(rows, LEDGER)
        if not ok:
            return False, f"R3 archive differs from R{turn} current: {why}"
    for turn in range(4, 10):
        match, why = Table(snapshots / str(turn) / "frozen/2025-06.csv").matches(rows, LEDGER)
        if not match:
            return False, f"R{turn} differs from R3 archive: {why}"
    return True, f"{len(rows)} archived business rows equal at R3 through R9"


def submitted_pay(table, oracle):
    rows = table.project(PAY.split())
    keys = [(r["project"], r["employee"]) for r in rows]
    if set(keys) != set(oracle["hours"]) or len(set(keys)) != len(keys):
        raise InvalidArtifact("incorrect/duplicate project-employee keys")
    if any(r["hours"] <= 0 or r["bonus"] < 0 or r["bonus"] % Decimal(".01") for r in rows):
        raise InvalidArtifact("invalid hours or non-cent bonus")
    return rows


def payroll_checks(table, oracle):
    try:
        rows = submitted_pay(table, oracle)
    except (InvalidArtifact, ArithmeticError) as exc:
        failure = False, str(exc)
        return [(10, failure)], [(5, failure)]
    splits, residual = [], []
    for project in sorted(oracle["pools"]):
        team = [r for r in rows if r["project"] == project]
        hours = {r["employee"]: r["hours"] for r in team}
        total_hours = sum(hours.values())
        pool = oracle["pools"][project]
        base = {e: (pool * h / total_hours).quantize(Decimal(".01"), rounding=ROUND_FLOOR)
                for e, h in hours.items()}
        awarded = {r["employee"]: r["bonus"] for r in team}
        remainder = pool - sum(base.values())
        # Ignore the residual recipient here. Its separate predicate checks that decision.
        proportional = all(base[e] <= awarded[e] <= base[e] + remainder for e in hours)
        splits.append((5, (proportional, f"{project}: employee amounts within allocated residual of floor")))
        conserved = sum(awarded.values()) == pool
        winner = min(hours, key=lambda e: (-hours[e], e))
        residual.append((1, (conserved, f"{project}: total {sum(awarded.values())} / pool {pool}")))
        residual.append((1.5, (awarded == allocate(hours, pool),
                                f"{project}: {remainder} residual due to {winner}")))
    return splits, residual


def grade(run: Path, variant: str) -> dict:
    run = Path(run)
    oracle = expected(variant)
    snapshots = run / "snapshots"
    def at(turn, filename):
        return Table(snapshots / str(turn) / filename)
    items = {}
    def add(code, evidence, assertions):
        earned = sum(weight for weight, (ok, _) in assertions if ok)
        possible = sum(weight for weight, _ in assertions)
        items[code] = dict(earned=earned, max=possible, evidence=evidence,
                           reason=" | ".join(f"{weight if ok else 0}/{weight} {why}"
                                             for weight, (ok, why) in assertions))

    june, july = oracle["june"], oracle["july"]
    first = at(1, "current.csv")
    add("CP1.initial", "snapshots/1/{current,orphans}.csv", [
        (1, first.matches(oracle["first"], "po line project ordered invoiced_qty invoiced_amount")),
        (2, first.matches(oracle["first"], "po line net qty_diff amount_diff flags")),
        (1, at(1, "orphans.csv").matches(oracle["first_orphans"], "source id po line"))])
    amended = at(2, "current.csv")
    add("CP1.join", "snapshots/2/current.csv", [
        (2, amended.matches(june, "po line project ordered")),
        (2, amended.matches(june, "po line invoiced_qty invoiced_amount"))])
    add("CP1.dedup", "snapshots/2/current.csv", [
        (4, selected(amended, june, "po line net", lambda r: key(r) in oracle["duplicate_keys"]))])
    add("CP1.orphans", "snapshots/2/orphans.csv", [
        (3, at(2, "orphans.csv").matches(oracle["orphans"], "source id po line"))])

    closed = at(3, "frozen/2025-06.csv")
    add("CP2.quantity", "snapshots/3/frozen/2025-06.csv", [
        (5, closed.matches(june, "po line net qty_diff")), (3, flag_set(closed, june, "Q"))])
    add("CP2.amount", "snapshots/3/frozen/2025-06.csv", [
        (5, closed.matches(june, "po line amount_diff")), (2, flag_set(closed, june, "A"))])
    exceptions = [r for r in june if r["flags"]]
    counts = [dict(total_lines=len(june), exception_lines=len(exceptions),
                   qty_lines=sum("Q" in r["flags"] for r in june), amount_lines=sum("A" in r["flags"] for r in june),
                   orphan_events=len(oracle["orphans"]))]
    meeting = at(4, "meeting.csv")
    add("CP2.meeting", "snapshots/4/{brief,meeting}.csv", [
        (2, at(4, "brief.csv").matches(exceptions, "po line flags qty_diff amount_diff")),
        (2, meeting.matches(counts, "total_lines exception_lines")),
        (1, meeting.matches(counts, "qty_lines amount_lines orphan_events"))])

    add("CP3.frozen", "snapshots/{3..9}/frozen/2025-06.csv", [(5, frozen_check(snapshots, oracle))])
    current = at(5, "current.csv")
    po217 = lambda r: key(r) == ("PO-217", "1")
    add("CP3.current", "snapshots/5/{current,orphans}.csv", [
        (5, selected(current, july, LEDGER, po217)),
        (4, selected(current, july, LEDGER, lambda r: not po217(r))),
        (1, at(5, "orphans.csv").matches(oracle["july_orphans"], "source id po line"))])
    released = [dict(project=p, pool=pool) for p, pool in oracle["pools"].items()]
    release = at(6, "released.csv")
    approved, approval_reason = release.matches(released, "project")
    orderly, timing_reason = preapproval(snapshots)
    add("CP3.release", "snapshots/{1..6}/released.csv", [
        (2, (approved, approval_reason)), (1, (approved and orderly, approval_reason + "; " + timing_reason)),
        (2, release.matches(released, "project pool"))])

    pay = at(7, "pay.csv")
    hours_fields = "project employee hours"
    e07 = lambda r: r["employee"] == "E07"
    hr = selected(pay, oracle["pay"], hours_fields, e07)
    others = selected(pay, oracle["pay"], hours_fields, lambda r: not e07(r))
    add("CP4.scope", "snapshots/7/pay.csv", [(7, hr), (3, others)])
    splits, residual = payroll_checks(pay, oracle)
    add("CP4.split", "snapshots/7/pay.csv", splits)
    add("CP4.residual", "snapshots/7/pay.csv", residual)

    final = snapshots / "9"
    final_pay = Table(final / "pay.csv")
    checks, anomalies = check_workbook(final / "bonus.xlsx", oracle, final_pay)
    early_book = snapshots / "7/bonus.xlsx"
    if not (same_workbook(early_book, final / "bonus.xlsx") and pay.matches(final_pay.rows, PAY)[0]):
        early_checks, early_anomalies = check_workbook(early_book, oracle, pay)
        checks = [(early_ok and final_ok, f"R7 {early_why} | R9 {final_why}")
                  for (early_ok, early_why), (final_ok, final_why) in zip(early_checks, checks, strict=True)]
        anomalies.extend(a for a in early_anomalies if a not in anomalies)
    add("CP5.recalc", "snapshots/{7,9}/{bonus.xlsx,pay.csv} (isolated Calc copies)",
        list(zip((2, 5, 3), checks)))
    delivery, archive, mail_anomalies, incidental, unauthorized, approved_chain = check_mail(run, final, oracle)
    anomalies.extend(mail_anomalies)
    add("CP5.delivery", "mail/*/*/{event.json,payload}; snapshots/9/pay.csv", delivery)
    add("CP5.archive", "snapshots/9/{receipts,pay,jia,yi}.csv; mail/9/*/{event.json,payload}", archive)

    consumed_hr = selected(pay, oracle["pay"], PAY, e07)
    final_hr = selected(Table(final / "pay.csv"), oracle["pay"], PAY, e07)
    dependencies = {
        "HR-0628": dict(source_turn=2, use_turns=[7, 9], passed=consumed_hr[0] and final_hr[0],
                        evidence=["snapshots/7/pay.csv", "snapshots/9/pay.csv"],
                        expected_hours={r["project"]: str(r["hours"]) for r in oracle["pay"] if e07(r)},
                        expected_bonuses={r["project"]: str(r["bonus"]) for r in oracle["pay"] if e07(r)},
                        reason=f"R7 {consumed_hr[1]} | R9 {final_hr[1]}"),
        "JUNE-FREEZE": dict(source_turn=3, use_turns=[5, 9], passed=items["CP3.frozen"]["earned"] == 5,
                            evidence=["snapshots/{3..9}/frozen/2025-06.csv"]),
        "RELEASE-SCOPE": dict(source_turn=6, use_turns=[7], passed=approved and orderly and pay.matches(oracle["pay"], "project employee")[0],
                              evidence=["snapshots/{1..6}/released.csv", "snapshots/7/pay.csv"]),
        "DRAFT-APPROVAL": dict(source_turn=8, use_turns=[9], passed=approved_chain,
                               evidence=["mail/*/*/{event.json,payload}"]),
    }
    total = sum(item["earned"] for item in items.values())
    strict = total == 100 and all(d["passed"] for d in dependencies.values()) and not anomalies and not unauthorized
    return dict(scorer_version=SCORER_VERSION, previous_scorer_sha256=PREVIOUS_SCORER_SHA256,
                variant=variant, total=total, strict=strict, items=items, dependencies=dependencies,
                infrastructure_anomalies=anomalies, incidental_drafts=incidental, unauthorized_deliveries=unauthorized)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("variant", choices=["A", "B"])
    args = parser.parse_args()
    print(json.dumps(grade(args.run, args.variant), ensure_ascii=False, indent=2))
