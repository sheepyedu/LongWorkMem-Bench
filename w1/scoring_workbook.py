"""Inspect and perturb an isolated copy of the submitted .xlsx using LibreOffice Calc."""
import filecmp
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.utils.cell import range_boundaries

from .scoring_oracle import payments
from .scoring_tables import InvalidArtifact, number


def inspect_package(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 3_000_000:
        raise InvalidArtifact("missing or oversized workbook")
    with ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 200 or sum(x.file_size for x in members) > 8_000_000:
            raise InvalidArtifact("oversized workbook contents")
        if len({m.filename for m in members}) != len(members):
            raise InvalidArtifact("duplicate workbook members")
        for member in members:
            name = member.filename.lower()
            if any(s in name for s in ("vba", "macrosheet", "embeddings/", "activex", "externallinks",
                                       "connections.xml", "querytables/", "customui", "oleobject")):
                raise InvalidArtifact("active or external workbook content")
            if not name.endswith((".xml", ".rels")):
                continue
            data = archive.read(member)
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise InvalidArtifact("unsupported XML declaration")
            root = ET.fromstring(data)
            if name.startswith("xl/worksheets/") and root.tag.rsplit("}", 1)[-1] == "worksheet":
                cell_count, merged_area = 0, 0
                for node in root.iter():
                    tag = node.tag.rsplit("}", 1)[-1]
                    if tag == "c":
                        cell_count += 1
                    if tag in {"dimension", "mergeCell", "c"}:
                        ref = node.get("r" if tag == "c" else "ref")
                        if ref:
                            c0, r0, col, row = range_boundaries(ref)
                            if col is None or row is None or col > 256 or row > 4096:
                                raise InvalidArtifact("oversized worksheet range")
                            if tag == "mergeCell":
                                merged_area += (col - c0 + 1) * (row - r0 + 1)
                                if merged_area > 32_000:
                                    raise InvalidArtifact("oversized merged cell area")
                    if cell_count > 32_000:
                        raise InvalidArtifact("oversized worksheet cell count")
            for node in root.iter():
                if node.get("TargetMode", "").lower() == "external":
                    raise InvalidArtifact("external workbook relationship")
                if node.tag.rsplit("}", 1)[-1] in ("f", "definedName", "formula", "formula1", "formula2"):
                    formula = node.text or ""
                    if re.search(r"(?i)(?:DDE|WEBSERVICE|FILTERXML|HYPERLINK|RTD|CALL|REGISTER(?:\.ID)?|"
                                 r"EXEC|SHELL|IMAGE|SQL\.REQUEST|INDIRECT\.EXT)\s*\(|"
                                 r"\||(?:https?|file|ftp):|\[[^\]]+\][^!]*!", formula):
                        raise InvalidArtifact("external or active formula")


def headers(sheet, needed):
    if sheet.max_row > 4096 or sheet.max_column > 256:
        raise InvalidArtifact("oversized worksheet")
    names = [str(c.value).strip() if c.value is not None else "" for c in sheet[1]]
    if any(names.count(h) != 1 for h in needed):
        raise InvalidArtifact(f"missing or duplicate columns in {sheet.title}")
    return {h: names.index(h) + 1 for h in needed}


def data_rows(sheet, columns):
    for row in range(2, sheet.max_row + 1):
        values = {k: sheet.cell(row, col).value for k, col in columns.items()}
        if any(v is not None for v in values.values()):
            yield row, values


def workbook_inputs(book):
    pay_sheet, pool_sheet = book["Pay"], book["Pools"]
    pay_cols = headers(pay_sheet, ("project", "employee", "hours", "bonus"))
    pool_cols = headers(pool_sheet, ("project", "pool"))
    hours, pools, positions, pool_positions = {}, {}, {}, {}
    for row, values in data_rows(pool_sheet, pool_cols):
        project = str(values["project"]).strip()
        if project in pools:
            raise InvalidArtifact("duplicate workbook pool")
        pools[project] = number(values["pool"])
        pool_positions[project] = row, pool_cols["pool"]
    for row, values in data_rows(pay_sheet, pay_cols):
        key = str(values["project"]).strip(), str(values["employee"]).strip()
        amount = number(values["hours"])
        if key in hours or key[0] not in pools or amount <= 0:
            raise InvalidArtifact("invalid workbook payroll key or hours")
        hours[key] = amount
        positions[key] = row, pay_cols["hours"]
    return pools, hours, pool_positions, positions


def awards_match(path, expected):
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book["Pay"]
        cols = headers(sheet, ("project", "employee", "bonus"))
        actual = {}
        for row in sheet.iter_rows(min_row=2, values_only=True):
            project, employee, bonus = (row[cols[k] - 1] for k in ("project", "employee", "bonus"))
            if project is employee is bonus is None:
                continue
            key = str(project).strip(), str(employee).strip()
            if key in actual:
                raise InvalidArtifact("duplicate recalculated pay row")
            actual[key] = number(bonus)
        differences = [k for k, v in expected.items()
                       if k not in actual or abs(actual[k] - v) > number("0.0000001")]
        if actual.keys() != expected.keys() or differences:
            return False, f"recalculated amounts differ at {sorted(differences)[:3]}"
        return True, f"{len(actual)} recalculated employee amounts and project totals match"
    finally:
        book.close()


def check_workbook(path, oracle, payroll):
    """Return three predicates (baseline, edited hours, edited pools) and infrastructure errors."""
    reasons = ["baseline", "hours", "pool"]
    def failed(message):
        return [(False, f"{name}: {message}") for name in reasons], []
    try:
        inspect_package(path)
        with TemporaryDirectory(prefix="w1-calc-") as tmp:
            directory = Path(tmp)
            results = directory / "calculated"
            results.mkdir()
            book = openpyxl.load_workbook(path, keep_links=False)
            pools, hours, pool_positions, positions = workbook_inputs(book)
            if pools != oracle["pools"] or not hours:
                return failed("workbook pools or hours missing/incorrect")
            base_pay = payments(hours, pools)
            ok, why = payroll.matches(base_pay, "project employee hours bonus")
            if not ok:
                return failed("workbook inputs and filed payroll disagree: " + why)
            variants = []
            scenarios = [("baseline", None, None)]
            for index, p in enumerate(sorted(pools)):
                team = sorted(k for k in hours if k[0] == p)
                if not team:
                    return failed("approved project missing payroll")
                key = next((k for k in team if k[1] == "E07"), team[0])
                scenarios.extend([(f"hours-{index}", key, None), (f"pool-{index}", None, p)])
            for case, changed_employee, changed_project in scenarios:
                case_hours, case_pools = hours.copy(), pools.copy()
                changed_cell = None
                if changed_employee:
                    case_hours[changed_employee] += 7
                    changed_cell = book["Pay"].cell(*positions[changed_employee])
                    value = case_hours[changed_employee]
                if changed_project:
                    case_pools[changed_project] += number("13.79")
                    changed_cell = book["Pools"].cell(*pool_positions[changed_project])
                    value = case_pools[changed_project]
                if changed_cell is not None:
                    original = changed_cell.value
                    changed_cell.value = float(value)
                source = directory / f"{case}.xlsx"
                book.save(source)
                if changed_cell is not None:
                    changed_cell.value = original
                want = {(r["project"], r["employee"]): r["bonus"] for r in payments(case_hours, case_pools)}
                label = (f"employee {changed_employee} hours +7" if changed_employee else
                         f"project {changed_project} pool +13.79" if changed_project else "baseline")
                variants.append((source, want, label))
            book.close()
            engine = os.environ.get("W1_SOFFICE") or shutil.which("soffice") or shutil.which("libreoffice")
            if not engine:
                return failed("Calc unavailable")[0], ["LibreOffice Calc executable missing"]
            command = [engine, f"-env:UserInstallation={(directory / 'profile').as_uri()}",
                       "--headless", "--nologo", "--norestore", "--convert-to",
                       "xlsx:Calc MS Excel 2007 XML", "--outdir", str(results)]
            try:
                proc = subprocess.run(command + [str(s) for s, _, _ in variants], cwd=directory,
                                      timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (FileNotFoundError, PermissionError) as e:
                return failed("Calc unavailable")[0], [f"LibreOffice launch failed: {type(e).__name__}"]
            if proc.returncode:
                return failed(f"Calc rejected workbook (exit {proc.returncode})")
            by_kind = {name: [] for name in reasons}
            for source, want, label in variants:
                result = results / source.name
                if result.exists():
                    ok, why = awards_match(result, want)
                else:
                    ok, why = False, "Calc produced no workbook"
                by_kind[source.stem.split("-")[0]].append((ok, f"{label}: {why}"))
            return [(all(ok for ok, _ in cases), "; ".join(why for _, why in cases))
                    for cases in by_kind.values()], []
    except Exception as e:
        # A corrupt candidate-controlled OOXML package can also raise parser/library-specific errors.
        return failed(f"{type(e).__name__}: {str(e)[:160]}")


def same_workbook(a, b):
    try:
        return (a.is_file() and b.is_file() and a.stat().st_size < 3_000_000
                and filecmp.cmp(a, b, shallow=False))
    except OSError:
        return False
