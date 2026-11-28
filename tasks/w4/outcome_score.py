"""Host-only candidate scorecard for frozen release-v2 evidence."""

import argparse
import json
from collections import Counter
from pathlib import Path

from .annex_grade import FIELDS, fields
from .format_review import review
from .grade import daytime_grade, manual_reader
from .office import attachment, events

# Each customer-facing action belongs to one release window, including quiet days.
RELEASES = (
    (3, 1, 3, 12),
    (4, 4, 4, 12),
    (6, 5, 6, 11),
    (9, 7, 9, 11),
    (10, 10, 10, 12),
    (11, 11, 12, 8),
)


def score(run):
    frozen = daytime_grade(run)
    if frozen["version"] not in ("release-v2", "release-v3"):
        raise ValueError("现场履约评分仅适用于 w4-release-v2")
    recovered = set(review(run, frozen)["eligible_expanded_claims"])
    read_manual = manual_reader(run)
    log = events(run, 12, None)
    if frozen["version"] == "release-v3":
        from .night import IDS

        log = [e for e in log if e["subject"] not in IDS]
    groups = []

    def facts(turn, name):
        return {
            k: c
            for g in frozen["details"]
            if g["turn"] == turn and g["group"] == name
            for k, c in g["checks"].items()
        }

    def add(turn, name, weight, cases, extras=()):
        denominator = len(cases) + len(extras)
        if not denominator:
            raise ValueError(f"缺少检查对象 R{turn} {name}")
        credit = sum(x["credit"] for x in cases.values()) / denominator
        groups.append(
            {
                "turn": turn,
                "group": name,
                "maximum": weight,
                "earned": weight * credit,
                "denominator": denominator,
                "cases": cases,
                "extras": sorted(extras),
            }
        )

    def table(turn, name, weight, sections):
        # A section represents one business assertion, sometimes requiring two linked fields.
        cases = {}
        extras = set()
        for sheet, columns, fraction in sections:
            rows = facts(turn, sheet)
            extras.update(k.split("/")[0] for k in rows if k.endswith("/多余行"))
            ids = {k.split("/")[0] for k in rows if k.endswith("/" + columns[0])}
            for case in sorted(ids):
                checks = {}
                for col in columns:
                    c = rows[f"{case}/{col}"]
                    checks[col] = {
                        **c,
                        "ok": c["ok"] or (col == "当时应发" and case in recovered),
                    }
                entry = cases.setdefault(case, {"credit": 0, "checks": {}})
                entry["credit"] += fraction * all(c["ok"] for c in checks.values())
                entry["checks"].update(checks)
        add(turn, name, weight, cases, extras)

    def dispatch(turn, start, end, weight, action):
        draft = action == "draft"
        routes = facts(turn, "草稿对象与次数" if draft else "发送对象与次数")
        terms = facts(turn, "冻结附件")
        annex = facts(turn, "现场附页")
        first = {}
        surplus = []
        for e in log:
            if e["action"] != action or not start <= e["turn"] <= end:
                continue
            case = e["subject"]
            if e["turn"] == turn and case in terms and case not in first:
                first[case] = e
            else:
                surplus.append(e["receipt"])
        cases = {}
        for k in sorted(terms):
            recipient = routes[k]["expected"][0]
            obj, term = terms[k]["expected"][0]
            station, voucher, seats = [
                annex[f"{k}/{col}"]["expected"][0] for col in FIELDS
            ]
            want = [recipient, obj, term, station, voucher, seats]
            got = [None] * len(want)
            if k in first:
                e = first[k]
                payload = attachment(run, e)
                got = [e["recipient"], *read_manual(payload), *fields(payload)]
            routed = got[:2] == want[:2]
            correct_site = got[3] == station
            # A zero allocation takes no seats at either station.
            correct_seats = got[5] == seats and (seats == "0" or correct_site)
            ratio = (
                (
                    0.3 * (got[2] == term)
                    + 0.3 * (correct_site and got[4] == voucher)
                    + 0.4 * correct_seats
                )
                if routed
                else 0.0
            )
            cases[k] = {
                "expected": want,
                "observed": got,
                "credit": ratio,
                "receipt": first[k]["receipt"] if k in first else None,
            }
        add(turn, "签发草稿" if draft else "实际履约", weight, cases, surplus)

    # Ten points for contemporaneous process evidence, including the draft.
    for t, sheet, weight, columns in [
        (1, "期初", 1, ("当前版",)),
        (1, "待办", 1, ("状态", "下一步")),
        (2, "变更", 0.5, ("处置",)),
        (4, "回执", 2, ("截点状态",)),
        (5, "通讯", 1, ("新发布", "旧件确认", "勘误")),
        (7, "排期", 1.5, ("生效日", "行动")),
        (8, "值班", 0.5, ("负责人",)),
    ]:
        table(t, sheet, weight, [(sheet, columns, 1)])
    dispatch(2, 2, 2, 2.5, "draft")
    for turn, start, end, weight in RELEASES:
        dispatch(turn, start, end, weight, "deliver")

    table(
        11,
        "历史授权",
        4,
        [
            ("追溯", ("当时应发",), 0.4),
            ("附页追溯", ("原应签主站", "原应签凭证"), 0.3),
            ("附页追溯", ("应配席位",), 0.3),
        ],
    )
    table(
        11,
        "历史实发",
        5,
        [("追溯", ("实际附件",), 0.5), ("附页追溯", ("原实发席位",), 0.5)],
    )
    table(
        11,
        "历史截点",
        4,
        [("追溯", ("确认数",), 0.5), ("附页追溯", ("截至4日实占",), 0.5)],
    )
    table(11, "现行义务", 2, [("追溯", ("现行时限",), 1)])
    table(
        12,
        "客户交割",
        4,
        [("交割", ("状态", "下一步"), 0.65), ("交割", ("责任邮箱",), 0.35)],
    )
    table(12, "站点交割", 5, [("席位交割", ("累计占用", "可用席位"), 1)])

    rounds = Counter()
    for g in groups:
        rounds[g["turn"]] += g["earned"]
    return {
        "scorecard": "w4-release-v2-outcomes-1",
        "frozen_total": frozen["total"],
        "total": round(sum(rounds.values()), 4),
        "rounds": [round(rounds[t], 6) for t in range(1, 13)],
        "groups": groups,
        "format_issues": frozen["format_issues"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    print(json.dumps(score(parser.parse_args().run), ensure_ascii=False, indent=2))
