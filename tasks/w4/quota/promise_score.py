"""Customer obligations are the primary unit. Retain every old atom for diagnosis."""

import re
import unicodedata
from collections import defaultdict

from .desk import DAYS
from .world import IDS

WEIGHTS = {"履约": 72, "客户通知": 10, "交班重算": 8, "交付证据": 8, "操作范围": 2}


def integer_matches(expected, observed):
    """Compare seat counts exactly while tolerating spreadsheet display formats."""
    if (
        not isinstance(expected, int)
        or isinstance(expected, bool)
        or isinstance(observed, bool)
    ):
        return False
    text = unicodedata.normalize("NFKC", str(observed)).strip()
    if len(text) > 64 or not re.fullmatch(r"[+-]?[0-9]+(?:\.0+)?", text):
        return False
    return int(text.split(".")[0]) == expected


def scorecard(atoms):
    groups = defaultdict(list)
    for a in atoms:
        field = a["field"]
        if field == "柜面实际席位":
            group = "履约"
        elif field == "授权动作范围" or a["case"] == "全台":
            group = "操作范围"
        elif field.startswith("预约-"):
            group = "交班重算"
        elif a["turn"] == 11 and (
            a["evidence"] == "全程客户邮箱" or field in ("原承诺", "新承诺", "实际兑现")
        ):
            group = "客户通知"
        else:
            group = "交付证据"
        groups[group].append(a)

    result = []
    for group, budget in WEIGHTS.items():
        items = groups[group]
        if not items:
            raise ValueError("缺少责任类别 " + group)
        denominator = sum(x["maximum"] for x in items)
        for x in items:
            weight = (
                budget / len(items)
                if group == "履约"
                else budget * x["maximum"] / denominator
            )
            result.append(
                {
                    **x,
                    "responsibility": group,
                    "maximum": weight,
                    "earned": weight if x["earned"] == x["maximum"] else 0,
                }
            )
    fulfil = groups["履约"]
    if {(x["turn"], x["case"]) for x in fulfil} != {
        (t, k) for t in DAYS for k in IDS
    } or len(fulfil) != len(DAYS) * len(IDS):
        raise ValueError("履约证据未覆盖固定客户与日期")
    hits = {(x["turn"], x["case"]) for x in fulfil if x["earned"] == x["maximum"]}
    return sorted(result, key=lambda x: x["id"]), {
        "customer_days_correct": len(hits),
        "customer_days": len(fulfil),
        "customers_always_correct": sum(all((t, k) in hits for t in DAYS) for k in IDS),
        "customers": len(IDS),
    }
