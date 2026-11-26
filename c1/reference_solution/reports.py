from collections import Counter

from migration import write_rows
from views import FIELDS, current


def report(conn, current_path, history_path):
    counts = Counter(row["dept"] for row in current(conn))
    write_rows(current_path, ("dept", "count"),
               ({"dept": dept, "count": counts[dept]} for dept in sorted(counts)))
    write_rows(history_path, FIELDS, current(conn, through=3, arrived_by=205))
