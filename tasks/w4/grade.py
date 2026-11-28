"""Host-only W4 evaluator. Source marker: W4_PRIVATE_ORACLE_7cf2."""

from collections import defaultdict
import json
import re
import unicodedata
from pathlib import Path
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from .scenario import (
    AUDITS,
    CODES,
    FIRST,
    LAST,
    NEW,
    TABS,
    UPDATE,
    address,
    object_id,
    opening_version,
)
from .office import attachment, events, status

POINTS = (5, 6, 13, 10, 3, 11, 4, 2, 9, 14, 17, 6)
CLOSING = (
    "P01",
    "P03",
    "P03-R",
    "L01-R",
    "L02-R",
    "N01",
    "N03",
    "T01",
    "U01",
    "U04",
    "L03-C",
)
OBJECTS = {k: (i, s) for k, i, s in FIRST + NEW + LAST + UPDATE}
OBJECTS.update(L01=(0, "A"), L02=(1, "B"), L03=(2, "A"))
ALIASES = {
    "已签收": "已确认",
    "待签收": "待确认",
    "未发送": "未发",
    "待审批": "待签",
    "无": "未发",
}
NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "七": 7, "八": 8, "十": 10}


def norm(value):
    s = "".join(
        unicodedata.normalize("NFKC", str(value if value is not None else "")).split()
    ).strip()
    for n, v in NUMBERS.items():
        s = re.sub(r"^" + n + r"(?=个?(工作日|自然日)$)", str(v), s)
    s = re.sub(r"^(\d+)(工作日|自然日)$", r"\1个\2", s)
    return ALIASES.get(s, s)


def days(i, s, t):
    if (i, s) == (0, "A") and t < 10:
        return 7
    if (i, s) == (1, "B"):
        return 5 if t < 10 else 8
    return 10


def current(i, t, role="new"):
    return address(i, role) if t >= 5 and i in (0, 1) else address(i)


def manual(data):
    text = unicodedata.normalize("NFKC", data.decode("utf-8-sig", errors="replace"))

    def field(k):
        vals = re.findall(
            r"^[ \t]*(?:[-*][ \t]+)?" + k + r"[ \t]*:[ \t]*([^\n]*?)[ \t]*$", text, re.M
        )
        return norm(vals[0]) if len(vals) == 1 else "条款无效"

    return field("对象"), field("换机时限")


def sheets(path, tabs=TABS):
    if path.is_dir():
        return {}, ["交接表为目录"]
    if not path.exists():
        return {}, ["缺交交接表"]
    try:
        with ZipFile(path) as archive:
            if sum(x.file_size for x in archive.infolist()) > 64 * 1024 * 1024:
                return {}, ["工作簿解压体积越限"]
        wb = load_workbook(path, read_only=True, data_only=True)
        result = {}
        errors = []
        try:
            for name, columns in tabs.items():
                if name not in wb:
                    errors.append("缺页:" + name)
                    continue
                if (wb[name].max_row or 0) > 10000 or (wb[name].max_column or 0) > 256:
                    errors.append("页超出业务台账范围:" + name)
                    continue
                rows = iter(wb[name].values)
                header = [norm(v) for v in next(rows, ())]
                if any(header.count(c) != 1 for c in columns):
                    errors.append("表头缺失或重复:" + name)
                    continue
                idx = [header.index(c) for c in columns]
                data = {}
                for row in rows:
                    cells = [norm(row[i]) if i < len(row) else "" for i in idx]
                    if not any(cells):
                        continue
                    key = cells[0]
                    data[key] = (
                        dict(zip(columns[1:], cells[1:])) if key not in data else {}
                    )
                result[name] = data
        finally:
            wb.close()
        return result, errors
    except OSError as exc:
        # openpyxl uses an errno-less OSError for a ZIP with no workbook part.
        # A host filesystem error must propagate as a technical failure.
        if exc.errno is not None:
            raise
        return {}, ["无效工作簿:" + str(exc)]
    except (
        BadZipFile,
        InvalidFileException,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        OverflowError,
        ParseError,
        SyntaxError,
        EOFError,
        RuntimeError,
    ) as exc:
        return {}, ["无效工作簿:" + type(exc).__name__]


def grade(run):
    run = Path(run)
    from . import annex, annex_grade as field

    manifest = run / "manifest.json"
    protocol = (
        json.loads(manifest.read_text()).get("protocol")
        if manifest.is_file()
        else "w4-release-v1"
    )
    if protocol not in ("w4-release-v1", "w4-release-v2"):
        raise ValueError("未知 W4 版本")
    v2 = protocol == "w4-release-v2"
    if not (run / "mail").is_dir():
        raise ValueError("缺少宿主邮箱证据，无法评分")
    all_events = events(run, 12, None)
    by = defaultdict(list)
    for e in all_events:
        by[e["subject"]].append(e)

    def sent(k, cut):
        return [e for e in by[k] if e["action"] == "deliver" and e["turn"] <= cut]

    def latest(k, cut):
        rows = sent(k, cut)
        return status(rows[-1] if rows else None, cut)

    def spec(k, i, s, t, role=None):
        recipient = current(i, t) if role is None else address(i, role)
        return (recipient, object_id(i, s), f"{days(i, s, t)}个工作日")

    first = {k: spec(k, i, s, 3) for k, i, s in FIRST if k not in ("P08", "P12")}
    r3_plan = field.allocation(run, all_events, 3, first) if v2 else {}
    details = []
    issues = {}
    states = {}
    for t in range(1, 13):
        snap = run / "snapshots" / str(t)
        if not snap.is_dir():
            raise ValueError(f"缺少轮末快照 R{t}，无法评分")
        wb, errors = sheets(
            snap / "交接.xlsx", {**TABS, **annex.EXTRA_TABS} if v2 else TABS
        )
        extra_weight = field.WEIGHTS.get(t, 0) if v2 else 0
        multiplier = (POINTS[t - 1] - extra_weight) / POINTS[t - 1]
        if errors:
            issues[t] = errors
        actions = [e for e in all_events if e["turn"] == t]

        def group(label, weight, checks, *, extra=False):
            if not extra:
                weight *= multiplier
            if not checks:
                raise ValueError("空检查组")
            hits = sum(bool(v["ok"]) for v in checks.values())
            details.append(
                dict(
                    turn=t,
                    group=label,
                    weight=weight,
                    earned=weight * hits / len(checks),
                    checks=checks,
                )
            )

        def check(want, got):
            return dict(expected=want, observed=got, ok=want == got)

        def table(name, weight, expected, *, extra=False):
            data = wb.get(name, {})
            out = {}
            for k, row in expected.items():
                for col, value in row.items():
                    actual = data.get(k, {}).get(col)
                    if col in ("实际附件", "原实发席位") and actual:
                        actual = ";".join(
                            sorted(norm(x) for x in re.split(r"[;、,]", actual))
                        )
                    if col == "生效日" and actual:
                        actual = re.sub(r"^(?:6月|06-)?0?(\d{1,2})日?$", r"\1", actual)
                    out[k + "/" + col] = check(str(value), actual)
            for k in data.keys() - expected.keys():
                if (
                    v2
                    and name == "通讯"
                    and k in CODES[2:]
                    and all(
                        data[k].get(c) == address(CODES.index(k))
                        for c in TABS["通讯"][1:]
                    )
                ):
                    continue
                out[k + "/多余行"] = check("无", "存在")
            group(name, weight, out, extra=extra)

        def mail(expected, route, content, action="deliver"):
            routing = {}
            terms = {}
            for k, target in expected.items():
                selected = [
                    e for e in actions if e["subject"] == k and e["action"] == action
                ]
                routing[k] = check([target[0]], [e["recipient"] for e in selected])
                actual = [list(manual(attachment(run, e))) for e in selected]
                terms[k] = check([list(target[1:])], actual)
                states[t, k] = routing[k]["ok"] and terms[k]["ok"]
            for e in actions:
                if e["subject"] not in expected or e["action"] != action:
                    routing[e["receipt"]] = check(
                        "无额外动作", e["action"] + "/" + e["subject"]
                    )
            group(
                "发送对象与次数" if action == "deliver" else "草稿对象与次数",
                route,
                routing,
            )
            group("冻结附件", content, terms)
            if v2:
                plan = field.allocation(run, all_events, t, expected)
                evidence = {}
                for k, expected_fields in plan.items():
                    rows = [
                        field.fields(attachment(run, e))
                        for e in actions
                        if e["subject"] == k and e["action"] == action
                    ]
                    for i, column in enumerate(field.FIELDS):
                        evidence[k + "/" + column] = check(
                            [expected_fields[i]], [r[i] for r in rows]
                        )
                group("现场附页", 3 if t == 11 else extra_weight, evidence, extra=True)

        if t == 1:
            table(
                "期初",
                3,
                {
                    object_id(i, s): {"当前版": opening_version(i, s)}
                    for _, i, s in FIRST
                },
            )
            table(
                "待办",
                2,
                {
                    k: dict(zip(TABS["待办"][1:], v))
                    for k, v in zip(
                        ("L01", "L02", "L03", "L04"),
                        [
                            ("已确认", "勘误"),
                            ("退信", "重投"),
                            ("待确认", "跟进"),
                            ("已确认", "关闭"),
                        ],
                    )
                },
            )
        elif t == 2:
            table(
                "变更",
                2,
                {
                    k: {"处置": v}
                    for k, v in [("HZ-A", "采用"), ("JL-B", "采用"), ("QH-A", "待签")]
                },
            )
            mail({k: first[k] for k in ("P01", "P02", "P04", "P09")}, 2, 2, "draft")
        elif t == 3:
            mail(first, 6, 7)
        elif t == 4:
            table("回执", 4, {k: {"截点状态": latest(k, t)} for k, _, _ in FIRST})
            fix = {
                k + "-R": spec(k, i, s, t, "backup")
                for k, i, s in FIRST
                if latest(k, 4) == "退信"
            }
            fix.update(
                {k + "-R": spec(k, *OBJECTS[k], t, "backup") for k in ("L01", "L02")}
            )
            mail(fix, 3, 3)
        elif t == 5:
            table(
                "通讯",
                3,
                {
                    CODES[i]: dict(
                        zip(
                            TABS["通讯"][1:],
                            [current(i, t), address(i), current(i, t, "review")],
                        )
                    )
                    for i in (0, 1)
                },
            )
        elif t == 6:
            mail({k: spec(k, i, s, t) for k, i, s in NEW}, 5, 6)
        elif t == 7:
            table(
                "排期",
                4,
                {
                    k: {"生效日": v, "行动": a}
                    for k, v, a in [
                        ("HZ-A", "10", "切换"),
                        ("JL-B", "10", "切换"),
                        ("QH-A", "待定", "待签"),
                    ]
                },
            )
        elif t == 8:
            table("值班", 2, {"东台": {"负责人": "赵宁"}, "西台": {"负责人": "吴禾"}})
        elif t == 9:
            mail({k: spec(k, i, s, t) for k, i, s in LAST}, 4, 5)
        elif t == 10:
            mail(
                {
                    k: spec(k, i, s, t)
                    for k, i, s in UPDATE
                    if days(i, s, 9) != days(i, s, 10)
                },
                6,
                8,
            )
        elif t == 11:
            expected = {}
            fix = {"L03-C": spec("L03", 2, "A", t)}
            for k in AUDITS:
                i, s = OBJECTS[k]
                original = sent(k, 3)
                actual = sorted(manual(attachment(run, e))[1] for e in original)
                target = first[k]
                expected[k] = dict(
                    zip(
                        TABS["追溯"][1:],
                        [
                            target[2],
                            ";".join(actual) or "未发",
                            str(sum(status(e, 4) == "已确认" for e in original)),
                            spec(k, i, s, t)[2],
                        ],
                    )
                )
                if (
                    len(original) != 1
                    or (original[0]["recipient"], *manual(attachment(run, original[0])))
                    != target
                    or (v2 and field.fields(attachment(run, original[0])) != r3_plan[k])
                ):
                    fix[k + "-C"] = (current(i, t, "review"), *spec(k, i, s, t)[1:])
            # The public audit sheet carries independent facts with fixed within-case weights.
            for col, w in zip(TABS["追溯"][1:], (3, 4, 3, 3)):
                table("追溯", w, {k: {col: v[col]} for k, v in expected.items()})
            mail(fix, 2, 2)
            if v2:
                table(
                    "附页追溯",
                    7,
                    field.historical(run, all_events, r3_plan),
                    extra=True,
                )
        else:
            expected = {}
            for k in CLOSING:
                i, _ = OBJECTS[k.split("-")[0]]
                st = latest(k, 12)
                owner = address(i) if st in ("待确认", "已确认") else current(i, t)
                expected[k] = dict(
                    zip(
                        TABS["交割"][1:],
                        [
                            st,
                            {
                                "已确认": "关闭",
                                "退信": "重投",
                                "待确认": "跟进",
                                "未发": "核实",
                            }[st],
                            owner,
                        ],
                    )
                )
            table("交割", 6, expected)
            if v2:
                occ = field.occupied(run, all_events, 12, 12)
                table(
                    "席位交割",
                    3,
                    {
                        p: {
                            "累计占用": occ[p],
                            "可用席位": field.capacity(12)[p] - occ[p],
                        }
                        for p in annex.POOLS
                    },
                    extra=True,
                )
        if t in (1, 5, 7, 8, 12) and actions:
            # Cap the loss for an unsolicited mailing at one point per quiet round.
            positive = sum(d["earned"] for d in details if d["turn"] == t)
            details.append(
                dict(
                    turn=t,
                    group="额外邮件",
                    weight=0,
                    earned=-min(1, positive),
                    checks={e["receipt"]: check("无", e["action"]) for e in actions},
                )
            )
    results = [
        round(sum(d["earned"] for d in details if d["turn"] == t), 6)
        for t in range(1, 13)
    ]
    pairs = [("P01", "N01"), ("P02", "N02"), ("P04", "N03"), ("P09", "N04")]
    eligible = [n for k, n in pairs if states.get((3, k))]
    return dict(
        version=protocol.removeprefix("w4-"),
        total=round(sum(d["earned"] for d in details), 4),
        rounds=results,
        delayed_retention={
            "correct": sum(states.get((6, n), False) for n in eligible),
            "eligible": len(eligible),
        },
        format_issues=issues,
        details=details,
    )
