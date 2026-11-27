"""Host-side payroll reconstruction, reference workbook and checkpoint scoring."""
from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from openpyxl import Workbook, load_workbook

from .advanced_pay import CENT, release
from .reference import PAY, read_csv, write_csv
from .scoring_tables import InvalidArtifact, Table, number
from .scoring_workbook import awards_match, inspect_package, same_workbook, workbook_inputs


def latest(rows, key_fields, timestamp, cutoff, accepted, history):
    """Choose the signed version as of the applicable cutoff in each plant or document."""
    eligible = [r for r in rows if r[timestamp] <= cutoff and r["decision"] in accepted]
    if history:
        # The office reference walks versions chronologically. The oracle below looks up each maximum.
        records = {}
        for row in sorted(eligible, key=lambda r: int(r["revision"])):
            records[tuple(row[k] for k in key_fields)] = row
        return records.values()
    groups = defaultdict(list)
    for row in eligible:
        groups[tuple(row[k] for k in key_fields)].append(row)
    return [max(versions, key=lambda row: int(row["revision"])) for versions in groups.values()]


def released(work, history=False):
    approved = (work / "inbox/FN-F72.eml").read_text(encoding="utf-8")
    projects = re.search(r"书面放行项目：([^。]+)", approved).group(1).split("、")
    register = read_csv(work / "input/财务会签/额度签署登记.csv")
    limits = defaultdict(Decimal)
    for row in latest(register, ["document"], "signed", "2025-07-31 18:00", {"签发", "撤销"}, history):
        if row["decision"] == "签发" and row["project"] in projects:
            limits[row["project"]] += Decimal(row["amount"])
    return dict(limits)


def reconstruct(work, level, history=False, rows=None, orders=None):
    pools = released(work, history)
    directory = work / "input"
    master = {r["employee"]: r["home"] for r in read_csv(directory / "薪酬制度/人员台账.csv")}
    notice = (work / "inbox/HR-0628.eml").read_text(encoding="utf-8")
    employee, origin, destination, effective = re.search(
        r"员工 (E\d+)，共享支援由(\S)转(\S)，生效日 (\d{4}-\d{2}-\d{2})", notice).groups()
    duties, caps = [], {}
    if level == 2:
        duties = read_csv(directory / "人事值班/签批派班.csv")
        caps = {(row["project"], row["employee"]): Decimal(row["cap"])
                for row in read_csv(directory / "财务会签/个人合同上限.csv")}
    if rows is None:
        rows = read_csv(directory / "工时中心/主账.csv") + read_csv(directory / "工时中心/补正.csv")
    hours, pending = defaultdict(Decimal), set()
    for r in latest(rows, ["site", "ticket"], "posted", "2025-08-03 18:00", {"已核", "作废"}, history):
        if r["decision"] == "作废" or not r["worked"].startswith("2025-07-"):
            continue
        emp, day, project = r["employee"], r["worked"], r["project"]
        if project == "共享":
            project = master[emp]
            if emp == employee:
                project = destination if day >= effective else origin
            for duty in duties:
                if duty["employee"] == emp and duty["from"] <= day <= duty["to"]:
                    project = duty["project"]
        key = r["site"], r["ticket"]
        quantity = Decimal(r["units"]) / (60 if r["unit"] == "MIN" else 1)
        parts = [(project, quantity)]
        if orders and key in orders:
            order = orders[key]
            moved = quantity * Decimal(order["percent"]) / 100
            parts = [(project, quantity - moved), (order["destination"], moved)]
        for target, h in parts:
            if h > 0 and target == "待查":
                pending.add(key)
            elif h > 0 and target in pools:
                hours[target, emp] += h
    return pools, dict(hours), caps, pending


def settlement_hours(hours, carry):
    if carry is None:
        return hours
    # June carry is already settled. July earns only the increase in quarter-to-date units.
    return {k: h + (max(0, carry[k] + h - 40) - max(0, carry[k] - 40)) / Decimal(2)
            for k, h in hours.items()}


def awards(hours, pools, caps, carry=None):
    """Allocate integral cents, including the case where giving away the residual would breach a cap."""
    hours = settlement_hours(hours, carry)
    result = {}
    for project, budget in pools.items():
        cents = int(budget * 100)
        team = {key: value for key, value in hours.items() if key[0] == project}
        def divide(staff, available):
            total = sum(staff.values())
            shares = {k: int(Fraction(h) * available / Fraction(total)) for k, h in staff.items()}
            winner = min(staff, key=lambda k: (-staff[k], k[1]))
            shares[winner] += available - sum(shares.values())
            return shares
        nominal = divide(team, cents)
        for person, cap in caps.items():
            if person not in team:
                continue
            limit = int(cap * 100)
            if cents * team[person] >= limit * sum(team.values()) or nominal[person] > limit:
                other = {k: h for k, h in team.items() if k != person}
                nominal = divide(other, cents - limit)
                nominal[person] = limit
        result.update({k: v * CENT for k, v in nominal.items()})
    return result


def pay_rows(hours, amounts):
    return [dict(project=p, employee=e, hours=value, bonus=amounts[p, e]) for (p, e), value in sorted(hours.items())]


def pristine(variant, level, seed):
    with TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "inbox").mkdir()
        for turn in (1, 2, 4, 6, 7):
            release(work, turn, variant, level, seed)
        pools, hours, caps, pending = reconstruct(work, level)
        return dict(pools=pools, hours=hours, caps=caps, pending=pending, pay=pay_rows(hours, awards(hours, pools, caps)))


def workbook(path, pools, hours, caps, carry=None):
    book = Workbook()
    pool_sheet = book.active
    pool_sheet.title = "Pools"
    pool_sheet.append(["project", "pool"])
    for p, amount in sorted(pools.items()):
        pool_sheet.append([p, amount])
    pay = book.create_sheet("Pay")
    pay.append([*PAY, "cap_cents", "pool_cents", "team_hours", "floor_cents", "primary_winner",
                "nominal_cents", "cap_binds", "fixed_cents", "fixed_hours", "new_floor", "eligible_winner"])
    if carry is not None:
        pay.cell(1, 16, "quarter_weight")
        pay.cell(1, 17, "prior_hours")
    end = len(hours) + 1
    def span(column):
        return f"${column}$2:${column}${end}"
    project, staff, limit, base, locked, redistributed = map(span, "ABEHKN")
    weight_col = "P" if carry is not None else "C"
    hrs = span(weight_col)
    for r, ((p, employee), value) in enumerate(sorted(hours.items()), 2):
        weight = f"{weight_col}{r}"
        share = f'COUNTIFS({project},A{r},{hrs},">"&{weight})+COUNTIFS({project},A{r},{hrs},{weight},{staff},"<"&B{r})'
        free = f'{project},A{r},{locked},0'
        free_rank = f'COUNTIFS({free},{hrs},">"&{weight})+COUNTIFS({free},{hrs},{weight},{staff},"<"&B{r})'
        pay.append([
            p, employee, value, f'=(N{r}+IF(O{r},F{r}-SUMIF({project},A{r},{redistributed}),0))/100',
            int(caps[p, employee] * 100) if (p, employee) in caps else -1,
            f'=ROUND(SUMIF(Pools!$A$2:$A$3,A{r},Pools!$B$2:$B$3)*100,0)',
            f'=SUMIF({project},A{r},{hrs})', f'=INT(F{r}*{weight}/G{r})', f'=IF(({share})=0,1,0)',
            f'=H{r}+IF(I{r},F{r}-SUMIF({project},A{r},{base}),0)',
            f'=IF(AND(E{r}>=0,OR(F{r}*{weight}>=E{r}*G{r},J{r}>E{r})),1,0)',
            f'=SUMIFS({limit},{project},A{r},{locked},1)', f'=SUMIFS({hrs},{project},A{r},{locked},1)',
            f'=IF(K{r},E{r},INT((F{r}-L{r})*{weight}/(G{r}-M{r})))', f'=IF(AND(K{r}=0,({free_rank})=0),1,0)'])
        if carry is not None:
            pay.cell(r, 16, f"=C{r}+(MAX(0,Q{r}+C{r}-40)-MAX(0,Q{r}-40))/2")
            pay.cell(r, 17, carry[p, employee])
        pay.cell(r, 4).number_format = "0.00"
    book.save(path)
    book.close()


def solve(work, turn, level):
    out = work / "out"
    if turn == 6:
        write_csv(out / "released.csv", ("project", "pool"),
                  [dict(project=p, pool=v) for p, v in released(work, history=True).items()])
    elif turn == 7:
        pools, hours, caps, pending = reconstruct(work, level, history=True)
        write_csv(out / "time_review.csv", ("site", "ticket"), [dict(site=s, ticket=t) for s, t in sorted(pending)])
        write_csv(out / "pay.csv", PAY, pay_rows(hours, awards(hours, pools, caps)))
        workbook(out / "bonus.xlsx", pools, hours, caps)


def recalc(path, submitted, oracle):
    """Each case edits a fresh copy. Grade the actual awards after Calc, not formula text."""
    try:
        inspect_package(path)
        book = load_workbook(path, keep_links=False)
        pools, hours, budget_cells, time_cells = workbook_inputs(book)
        if pools.keys() != oracle["pools"].keys() or hours.keys() != oracle["hours"].keys():
            raise InvalidArtifact("released projects or project-employee roster differ")
        if any(v <= 0 or v % CENT for v in pools.values()):
            raise InvalidArtifact("pool must be a positive amount in whole cents")
    except Exception as exc:
        return [(0, str(exc)[:160]) for _ in range(3)]
    engine = os.getenv("W1_SOFFICE") or shutil.which("soffice") or shutil.which("libreoffice")
    if not engine:
        book.close()
        raise RuntimeError("LibreOffice is required to verify live payroll calculations")
    with TemporaryDirectory(prefix="advanced-pay-calc-") as tmp:
        root = Path(tmp)
        calculated = root / "converted"
        calculated.mkdir()
        # Check all editable hours in a set of isolated workbooks, plus both sides of each contractual ceiling.
        cases = [("base", None, None)]
        baseline = awards(hours, pools, oracle["caps"], oracle.get("carry"))
        for key, value in sorted(hours.items()):
            changed = value + Decimal("5.25")
            def changes_awards(value):
                trial = {**hours, key: value}
                return awards(trial, pools, oracle["caps"], oracle.get("carry")) != baseline

            if not changes_awards(changed):
                # A capped employee may not earn more, and a tiny pool may pay only the leading
                # employee. Probe both sides and count only edits which actually change an award.
                other_hours = sum(h for k, h in hours.items() if k[0] == key[0] and k != key)
                alternatives = (other_hours / Decimal("10000"), other_hours * 10,
                                other_hours / Decimal("1e18"))
                changed = next((value for value in alternatives if changes_awards(value)), None)
            if changed is not None:
                cases.append(("hours", key, changed))
            if "carry" in oracle:
                threshold = 40 - oracle["carry"][key]
                if threshold > 0:
                    opposite = threshold / 2 if value > threshold else threshold + 6
                    if changes_awards(opposite):
                        cases.append(("hours", key, opposite))
        for p, pool in sorted(pools.items()):
            cases.append(("pool", p, pool + Decimal("39.43")))
            if oracle["caps"]:
                low = Decimal("25.03") if pool != Decimal("25.03") else Decimal("12.57")
                cases.extend([("pool", p, low), ("pool", p, pool * 7)])
        wants, arguments = [], []
        try:
            for index, (kind, key, change) in enumerate(cases):
                edit_hours, edit_pools = hours.copy(), pools.copy()
                cell = None
                if kind == "hours":
                    edit_hours[key] = change
                    cell = book["Pay"].cell(*time_cells[key])
                elif kind == "pool":
                    edit_pools[key] = change
                    cell = book["Pools"].cell(*budget_cells[key])
                if cell:
                    original = cell.value
                    cell.value = float(change)
                name = root / f"case-{index:03}.xlsx"
                book.save(name)
                if cell:
                    cell.value = original
                arguments.append(str(name))
                wants.append((kind, str(key), name.name, awards(edit_hours, edit_pools, oracle["caps"], oracle.get("carry"))))
        except Exception as exc:
            return [(0, f"invalid calculation inputs: {str(exc)[:100]}") for _ in range(3)]
        finally:
            book.close()
        command = [engine, f"-env:UserInstallation={(root / 'profile').as_uri()}", "--headless", "--nologo",
                   "--norestore", "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(calculated), *arguments]
        try:
            subprocess.run(command, cwd=root, capture_output=True, timeout=100, check=False)
        except OSError as exc:
            raise RuntimeError("Failed to launch LibreOffice for payroll verification") from exc
        except subprocess.TimeoutExpired:
            return [(0, "workbook timed out in Calc") for _ in range(3)]
        outcomes = defaultdict(list)
        for kind, key, name, expected in wants:
            try:
                ok, _ = awards_match(calculated / name, expected)
            except Exception:
                ok = False
            if kind == "base":
                ok = ok and pools == oracle["pools"] and hours == oracle["hours"] and submitted.matches(oracle["pay"], PAY)[0]
            outcomes[kind].append((key, ok))
        result = []
        for kind in ("base", "hours", "pool"):
            observations = outcomes[kind]
            failed = [key for key, ok in observations if not ok]
            passed = len(observations) - len(failed)
            result.append((passed / len(observations) if observations else 0, f"{passed}/{len(observations)} Calc {kind} cases; failed {failed[:4]}"))
        return result


def keyed_rows(table, keys):
    if table.error or not set(keys) <= set(table.headers):
        return {}, set()
    groups = defaultdict(list)
    for row in table.rows:
        groups[tuple(row[k] for k in keys)].append(row)
    return {k: rows[0] for k, rows in groups.items() if len(rows) == 1}, set(groups)


def numeric(row, field):
    try:
        return number(row.get(field))
    except InvalidArtifact:
        return None


def grade(run, variant, level, seed, *, oracle=None):
    if oracle is None:
        oracle = pristine(variant, level, seed)
    pools, hours, pending = oracle["pools"], oracle["hours"], oracle["pending"]
    snap = run / "snapshots"
    release_table = Table(snap / "6/released.csv")
    released_rows, projects = keyed_rows(release_table, ["project"])
    scope = {(p,) for p in pools}
    r7 = Table(snap / "7/pay.csv")
    paid, keys = keyed_rows(r7, ["project", "employee"])
    time_table = Table(snap / "7/time_review.csv")
    queried, submitted_queries = keyed_rows(time_table, ["site", "ticket"])
    checks = {}

    def fraction(name, weight, correct, denominator, source):
        checks["pay." + name] = (round(weight * correct / denominator, 4) if denominator else 0,
                                  weight, f"{source}: {correct}/{denominator}")

    fraction("release_scope", 2, len(set(released_rows) & scope), len(projects | scope), "R6 released projects")
    fraction("released_pool", 3, sum(numeric(released_rows.get((p,), {}), "pool") == v for p, v in pools.items()),
             len(pools), "R6 signed amount at cutoff")
    fraction("roster", 3, len(set(paid) & hours.keys()), len(keys | hours.keys()), "R7 unique project-employee rows")
    fraction("pending_tickets", 3, len(queried.keys() & pending), len(submitted_queries | pending), "R7 plant and ticket")
    for employee_test, name, weight in [(True, "transfer_hours", 4), (False, "other_hours", 5)]:
        group = {k: v for k, v in hours.items() if (k[1] == "E07") == employee_test}
        fraction(name, weight, sum(numeric(paid.get(k, {}), "hours") == v for k, v in group.items()), len(group),
                 "R7 project hours by date and signed version")
    sums, bonuses = 0, 0
    for p, budget in pools.items():
        team = {k for k in hours if k[0] == p}
        submitted_h = {k: numeric(paid.get(k, {}), "hours") for k in team}
        actual = {k: numeric(paid.get(k, {}), "bonus") for k in team}
        correct_keys = team == {k for k in keys if k[0] == p} and team <= paid.keys()
        if correct_keys and all(v is not None and v > 0 for v in submitted_h.values()):
            expected = awards(submitted_h, {p: budget}, oracle["caps"], oracle.get("carry"))
        else:
            expected = {(r["project"], r["employee"]): r["bonus"] for r in oracle["pay"] if r["project"] == p}
        bonuses += sum(actual[k] == expected[k] for k in team)
        if correct_keys and all(v is not None and v >= 0 and v % CENT == 0 for v in actual.values()):
            sums += sum(actual.values()) == budget
    fraction("individual_allocation", 5, bonuses, len(hours), "R7 employee awards under declared hours and official terms")
    fraction("conserved_pools", 2, sums, len(pools), "R7 project totals")
    early, final = snap / "7/bonus.xlsx", snap / "9/bonus.xlsx"
    result = recalc(early, r7, oracle)
    r9 = Table(snap / "9/pay.csv")
    if not (same_workbook(early, final) and r7.matches(r9.rows, PAY)[0] and not r9.error):
        later = recalc(final, r9, oracle)
        result = [(min(e[0], f[0]), f"R7 {e[1]} / R9 {f[1]}") for e, f in zip(result, later, strict=True)]
    for (ratio, reason), kind, weight in zip(result, ["baseline", "edited_hours", "edited_pools"], [2, 3, 3], strict=True):
        checks["pay.workbook_" + kind] = round(ratio * weight, 4), weight, reason
    return checks
