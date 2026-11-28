"""Host-only v3 evaluation from frozen customer mail and handover workbooks. W4_NIGHT_GRADER_3a9"""

from collections import defaultdict
import io
import json
import os
import re
import subprocess
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from tasks.w1.scoring_workbook import inspect_package, InvalidArtifact
from . import night
from .annex import POOLS
from .annex_grade import debit
from .grade import current, norm, sheets
from .office import attachment, events, status
from .scenario import address


def grant(k, t):
    n = night.BASE[k]
    for batch, obj, kind, start, value in night.AMENDMENTS:
        if obj == night.obj(k) and batch <= t and start <= t and kind == "签发":
            n = value
    return n


def history(k):
    i = night.IDS.index(k)
    old = night.OLD[i]
    replies = [(day, st) for j, day, st in night.REPLIES if j == i + 1]

    def at(t):
        return max(
            [(day, st) for day, st in replies if day <= t],
            default=(0, "未发" if old is None else "待确认"),
        )[1]

    if grant(k, 11) == 0:
        action = "暂缓"
    elif old is None:
        action = "首发"
    elif at(11) == "退信":
        action = "重投"
    elif old != grant(k, 3):
        action = "勘误"
    else:
        action = "关闭" if at(11) == "确认" else "跟进"
    return [
        grant(k, 3),
        old if old is not None else "未发",
        at(4),
        grant(k, 11),
        action,
    ]


def inputs(run, log, t):
    cap = dict(zip(POOLS, night.CAP))
    if t >= 9:
        cap["东港"] -= 3
        cap["北仓"] += 3
    if t >= 12:
        cap["西湾"] -= 2
        cap["南站"] += 2
    carried = defaultdict(int)
    for e in log:
        if e["turn"] == 3 and e["action"] == "deliver":
            carried[e["subject"]] += debit(run, e, 4)[1]
    demands = {
        k: max(
            0, grant(k, t) - carried["P" + k[1:]] - (2 if t == 12 and k == "H08" else 0)
        )
        for k in night.QUEUE
    }
    if t >= 9:
        demands["H03"] = 0
    if t == 12:
        demands["H07"] = 0
    return cap, demands


def allocation(cap, demands):
    left = cap.copy()
    result = {}
    for k in night.QUEUE:
        site = night.SITE[k]
        n = min(left[site], demands[k])
        result[k] = [n, demands[k] - n]
        left[site] -= n
    return result


# No host filesystem mount, no network, only submitted workbook copies enter this container.
CALC = """import sys,io,json,subprocess,pathlib,zipfile
from openpyxl import load_workbook
d=pathlib.Path('/tmp/jobs');d.mkdir();out=d/'out';out.mkdir()
with zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())) as z:z.extractall(d)
files=sorted(d.glob('*.xlsx'))
subprocess.run(['libreoffice','--headless','--convert-to','xlsx','--outdir',str(out),*map(str,files)],stdout=sys.stderr,check=True,timeout=55)
ans={}
for p in files:
 b=load_workbook(out/p.name,read_only=True,data_only=True)
 ans[p.stem]=list(b['队列'].iter_rows(min_row=2,max_row=13,min_col=4,max_col=5,values_only=True))
 b.close()
print(json.dumps(ans,default=str))
"""


def recalculate(files, image):
    packet = io.BytesIO()
    with ZipFile(packet, "w") as z:
        for name, data in files.items():
            z.writestr(name + ".xlsx", data)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "96",
        "--memory",
        "640m",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=128m",
        "-e",
        "HOME=/tmp",
        "--pull=never",
        image,
        "python3",
        "-c",
        CALC,
    ]
    result = subprocess.run(
        cmd, input=packet.getvalue(), capture_output=True, timeout=75
    )
    if result.returncode:
        raise RuntimeError(
            "Calc 复评未完成，请保留原交付重放："
            + result.stderr.decode(errors="replace")[-500:]
        )
    return json.loads(result.stdout)


def booking(path, cap, demands, image):
    try:
        inspect_package(path)
        book = load_workbook(path)
        try:
            cs, q = book["容量"], book["队列"]
            if [c.value for c in cs[1][:2]] != ["夜站", "容量"] or [
                c.value for c in q[1][:5]
            ] != ["案号", "夜站", "需求", "实际安排", "未排"]:
                raise InvalidArtifact("交班接口列标题错误")
            if [r[0].value for r in cs["A2:A5"]] != list(POOLS) or [
                r[0].value for r in q["A2:A13"]
            ] != list(night.QUEUE):
                raise InvalidArtifact("交班接口键或顺序错误")
            if [r[0].value for r in q["B2:B13"]] != [
                night.SITE[k] for k in night.QUEUE
            ]:
                raise InvalidArtifact("交班接口夜站错误")
            gotcap = {p: cs.cell(i, 2).value for i, p in enumerate(POOLS, 2)}
            gotd = {k: q.cell(i, 3).value for i, k in enumerate(night.QUEUE, 2)}
            # Keep the submitted baseline untouched. Two independent edit copies
            # cover both capacity and per-case changes, including unaffected stations.
            scenarios = {
                "baseline": (cap, demands),
                "transfer": (dict(cap), dict(demands)),
                "cancel": (dict(cap), dict(demands)),
            }
            scenarios["transfer"][0]["东港"] = 0
            scenarios["transfer"][0]["南站"] += 7
            if allocation(*scenarios["transfer"]) == allocation(cap, demands):
                # No backlog can react to a pure capacity change. Include an incoming request.
                scenarios["transfer"][1]["H04"] += 3
            scenarios["cancel"][1]["H08"] = 0
            scenarios["cancel"][1]["H07"] += 5
            files = {"baseline": path.read_bytes()}
            for name in ("transfer", "cancel"):
                c, d = scenarios[name]
                for i, p in enumerate(POOLS, 2):
                    cs.cell(i, 2).value = c[p]
                for i, k in enumerate(night.QUEUE, 2):
                    q.cell(i, 3).value = d[k]
                buf = io.BytesIO()
                book.save(buf)
                files[name] = buf.getvalue()
        finally:
            book.close()
    except (
        InvalidArtifact,
        BadZipFile,
        ParseError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        EOFError,
        OverflowError,
    ) as exc:
        return 0, 0, {"format": type(exc).__name__ + ": " + str(exc)[:130]}
    except OSError as exc:
        if exc.errno is not None:
            raise
        return 0, 0, {"format": str(exc)}
    raw = recalculate(files, image)
    baseline = allocation(cap, demands)

    def same_num(v, n):
        return type(v) in (float, int) and v == n

    correct_inputs = [same_num(gotcap[p], cap[p]) for p in POOLS] + [
        same_num(gotd[k], demands[k]) for k in night.QUEUE
    ]
    evidence = {
        "inputs": {
            "expected": [cap, demands],
            "observed": json.loads(json.dumps([gotcap, gotd], default=str)),
        },
        "scenarios": {},
    }
    ratios = []
    for name, (c, d) in scenarios.items():
        expected = allocation(c, d)
        ok = {}
        for k, obs in zip(night.QUEUE, raw[name], strict=True):
            ok[k] = all(same_num(x, y) for x, y in zip(obs, expected[k], strict=True))
        evidence["scenarios"][name] = {
            "expected": expected,
            "observed": dict(zip(night.QUEUE, raw[name])),
        }
        if name == "baseline":
            actual = 0.4 * sum(correct_inputs) / len(correct_inputs) + 0.6 * sum(
                ok.values()
            ) / len(ok)
        else:
            changed = [k for k in ok if expected[k] != baseline[k]]
            unchanged = [k for k in ok if expected[k] == baseline[k]]
            if not changed:
                raise ValueError("重算样例缺少变化案件")
            # Static outputs cannot pass the change test merely by matching untouched rows.
            ratios.append(
                sum(ok[k] for k in changed)
                / len(changed)
                * sum(ok[k] for k in unchanged)
                / len(unchanged)
            )
    return actual, sum(ratios) / len(ratios), evidence


def score(run):
    from .outcome_score import score as daytime

    run = Path(run)
    meta = json.loads((run / "manifest.json").read_text())
    image = os.getenv("W4_CALC_IMAGE") or meta.get("image") or "longworkmem-release:1"
    base = daytime(run)
    log = events(run, 12, None)
    groups = [
        dict(
            turn=t,
            group="日间履约",
            weight=sum(g["maximum"] for g in base["groups"] if g["turn"] == t) * 0.4,
            earned=sum(g["earned"] for g in base["groups"] if g["turn"] == t) * 0.4,
        )
        for t in range(1, 13)
    ]

    def add(t, label, weight, ratio, evidence):
        groups.append(
            dict(
                turn=t,
                group=label,
                weight=weight,
                earned=weight * ratio,
                evidence=evidence,
            )
        )

    for t in (8, 9, 12):
        cap, demands = inputs(run, log, t)
        a, b, ev = booking(
            run / "snapshots" / str(t) / "夜班预约.xlsx", cap, demands, image
        )
        add(t, "夜班当日安排", 5, a, ev)
        add(t, "交班后变更重算", 5, b, {"source": "同日夜班当日安排.scenarios"})
    grouped = defaultdict(list)
    for e in log:
        if e["subject"] in night.IDS and e["action"] == "deliver":
            grouped[e["subject"]].append(e)
    for t, tab, weight in [(11, "夜班异议", 12), (12, "夜班结班", 6)]:
        wb, issues = sheets(
            run / "snapshots" / str(t) / "交接.xlsx", {tab: night.HISTORY[tab]}
        )
        rows = wb.get(tab, {})
        cells = {}
        for k in night.IDS:
            sent = grouped[k]
            last = sent[-1] if sent else None
            expected = (
                history(k)
                if t == 11
                else [len(sent), last["receipt"] if last else "无", status(last, t)]
            )
            obs = [rows.get(k, {}).get(col) for col in night.HISTORY[tab][1:]]
            cells[k] = {
                "expected": expected,
                "observed": obs,
                "credit": sum(norm(a) == b for a, b in zip(expected, obs))
                / len(expected),
            }
        add(
            t,
            tab,
            weight,
            sum(r["credit"] for r in cells.values())
            / len(rows.keys() | set(night.IDS)),
            {"cases": cells, "issues": issues},
        )
    required = {}
    extra = []
    for k in night.IDS:
        i = night.IDS.index(k) // 2
        act = history(k)[-1]
        dest = {
            "首发": current(i, 11),
            "勘误": current(i, 11, "review"),
            "重投": address(i, "backup"),
        }.get(act)
        candidates = [e for e in grouped[k] if e["turn"] == 11]
        if dest:
            e = candidates[0] if candidates else None
            got = {}
            if e:
                val = attachment(run, e).decode("utf-8-sig", errors="replace")
                for col in ("对象", "处置", "夜班额度"):
                    matches = re.findall(
                        r"^\s*" + col + r"\s*[:：]\s*([^\n]+?)\s*$", val, re.M
                    )
                    got[col] = norm(matches[0]) if len(matches) == 1 else None
            want = {"对象": night.obj(k), "处置": act, "夜班额度": str(grant(k, 11))}
            required[k] = {
                "recipient": dest,
                "expected": want,
                "observed": got,
                "actual_recipient": e["recipient"] if e else None,
                "credit": (
                    sum(got.get(c) == v for c, v in want.items()) / 3
                    if e and e["recipient"] == dest
                    else 0
                ),
            }
        else:
            e = None
        extra.extend(x["receipt"] for x in grouped[k] if x != e)
    add(
        11,
        "夜班实际补救",
        12,
        sum(x["credit"] for x in required.values()) / (len(required) + len(extra)),
        {"required": required, "extra": sorted(extra)},
    )
    return dict(
        version="release-v3",
        total=round(sum(g["earned"] for g in groups), 4),
        rounds=[
            round(sum(g["earned"] for g in groups if g["turn"] == t), 6)
            for t in range(1, 13)
        ],
        details=groups,
        daytime=base,
    )
