"""Bounded, order-independent inspection of untrusted W1 submission tables."""
import csv
import io
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path


class InvalidArtifact(ValueError):
    pass


NUMERIC = set("ordered net invoiced_qty invoiced_amount qty_diff amount_diff pool "
              "hours bonus total_lines exception_lines qty_lines amount_lines orphan_events".split())
MAX_BYTES = 2 * 1024 * 1024
GROUPED_NUMBER = re.compile(r"[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:[.][0-9]+)?")


def number(value):
    try:
        text = str(value).strip()
        if "," in text and GROUPED_NUMBER.fullmatch(text):
            text = text.replace(",", "")
        n = Decimal(text)
        if n.is_finite() and n.adjusted() <= 12 and n.as_tuple().exponent >= -24:
            return n
    except (InvalidOperation, ValueError):
        pass
    raise InvalidArtifact(f"invalid numeric value {str(value)[:48]!r}")


def cell(field, value):
    if field in NUMERIC:
        return number(value)
    if value is None:
        raise InvalidArtifact(f"missing {field}")
    s = str(value).strip()
    if field == "flags" and sorted(s) == ["A", "Q"]:
        return "QA"
    return s


def read_csv(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise InvalidArtifact("missing, nonregular, or oversized file")
    with path.open("rb") as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise InvalidArtifact("oversized file")
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    headers = [h.strip() for h in next(reader, [])]
    if not headers or "" in headers or len(headers) != len(set(headers)):
        raise InvalidArtifact("invalid or duplicate headers")
    rows = []
    for values in reader:
        if not values:  # blank physical line
            continue
        if len(values) != len(headers) or len(rows) >= 12000:
            raise InvalidArtifact("ragged or oversized table")
        rows.append(dict(zip(headers, (v.strip() for v in values))))
    return headers, rows


class Table:
    def __init__(self, path):
        self.path = path
        self.headers, self.rows, self.error = [], [], None
        try:
            self.headers, self.rows = read_csv(path)
        except (OSError, ValueError, csv.Error) as e:
            self.error = str(e)[:160]

    def project(self, fields, *, predicate=None):
        if self.error:
            raise InvalidArtifact(self.error)
        missing = set(fields).difference(self.headers)
        if missing:
            raise InvalidArtifact(f"missing columns {sorted(missing)}")
        # Scope by normalized business IDs before validating numeric cells in that group.
        rows = self.rows if predicate is None else filter(predicate, self.rows)
        return [{k: cell(k, row[k]) for k in fields} for row in rows]

    def matches(self, expected, fields, *, exact_headers=False, predicate=None):
        """Return a predicate and an inspectable explanation. Multisets catch duplicates."""
        fields = fields.split() if isinstance(fields, str) else fields
        try:
            if exact_headers and set(self.headers) != set(fields):
                raise InvalidArtifact("unexpected column set")
            actual = self.project(fields, predicate=predicate)
            if predicate:
                expected = [r for r in expected if predicate(r)]
            def counts(rows):
                return Counter(tuple(cell(k, row[k]) for k in fields) for row in rows)
            got, want = counts(actual), counts(expected)
        except (ValueError, KeyError) as e:
            return False, str(e)
        if got == want:
            return True, f"{len(actual)} rows match fields {', '.join(fields)}"
        def sample(diff):
            return [[str(value)[:64] for value in key] for key in list(diff)[:2]]
        return False, f"missing {sample(want - got)}; extra {sample(got - want)}"
