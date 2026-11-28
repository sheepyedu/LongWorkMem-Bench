"""Public business inputs and deterministic staged desk for calendar-evolution-v1."""

import csv
from datetime import date, timedelta
import hashlib
from pathlib import Path
import tarfile

from tasks.c1.sandbox import WRITABLE
from tasks.c2.scenario import write

CHANNELS = ("A", "B", "C", "D")
VERSION = "calendar-evolution-v1"
ARCHIVE = Path(__file__).with_name("fixtures") / "legacy-release.tar.gz"
ARCHIVE_SHA = "d8d852b04a684c8696b96014d3754401b7344935dcacf5ea94887a0b0b8ab4c3"
DAYS = ["2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"]
LATE = ["2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09"]
PROMPTS = [
    "接手既有门户。门户 V1 旧项目仍在线。修复长区间无声截断，给 /api/events 增加可复跑的分页兼容入口，参见 input/contracts/paging.md。",
    "接入合作方新组合，按上线单的合同登记每周一的场次。实现可重入导入与按业务日、已知版本查询的排期内核。旧门户必须继续工作。当前发布版本号为 2。",
    "双版本上线：使用身份登记册给旧端和新端提供同一场次的稳定身份，接通 HTTP v2 和 ICS 生成器。新增迁移不得重写旧 UID 或报名。",
    "向 A、B、C、D 四端发布三月四个服务日的首发。请让发布包可从程序重建。完成后保留可供客服引用的实际交付记录。",
    "客服要核对伦敦门店所见时间。实现只读查询入口并交 input/support.json 所列问题的预览。旧投递资料今天已封存，核对时可按档案索引读取；不要通知客户。",
    "临时上线：按本期新批复处理临时窗口、单场移期和跨频道覆盖。对比真实下游，仅投当前差量。导入、导出和门户均应反映新口径。",
    "变更委员会驳回上一版的一部分。按撤回文件处理各端的覆盖链；请生成 out/plan-频道.ics 四份相对已收状态的待发包，先不要发送。",
    "刚才队列中断，有两项超时。接手真实回执、归档和待发包，恢复缺件。实现可重跑的差量入口，补齐三月交付，再执行一次核对，避免重复通知。",
    "交接上线：从源码与数据库备份启动干净实例；导入秋季追加工单。给四端发布秋季四个服务日，交出完整 out/backup.sqlite 和 out/new-C.ics。旧链接、历史版本和协议身份继续有效。",
    "客户对之前的发布有争议。交付可复跑的追溯程序和 out/inquiry.json，逐笔还原问题所定版本的应发、实收与当时未结事项。以实际历史为准。此次只读。",
]
GUIDE = """工程工位。project/ 是真实部署的旧门户与回归套件，data/portal.sqlite 是其签收备份，旧代码与报名需长期可用。较早交接资料描述旧产品；本次上线使用 contracts、version.txt 和分轮来件。可写 project、data、scratch、notes、out；input 只读。shell 位于无外网 Docker，每次独立，文件持续。python3 project/http_read.py URL 可通过真实 HTTP 访问门户。PORTAL_DB 指定数据库位置。发布工具 publish(channel,key,file) 读取 out/ 下的 ICS；同键同语义重试无副作用，不同内容不得复用键。receipts(channel) 读取在线批次，较早批次转入按编号索引的 input/vault/。每个新 key 都会通知客户。所有时间按 ISO8601 明示时区；业务版本为逻辑轮次，截止含端点。每轮具体接口见 input/contracts 与当天来件。档案中 draft/stale/training 不构成当前授权。可保留自己的索引。
"""
SITES = [
    ("N84", "America/New_York", "09:45", "wall"),
    ("Q29", "Europe/London", "15:00", "utc"),
    ("U56", "Europe/Berlin", "08:20", "wall"),
    ("J31", "Australia/Sydney", "01:30", "utc"),
]


def specs():
    return [
        dict(code=c, sid="line-" + str(401 + i), zone=z, clock=h, basis=b, weekday=0)
        for i, (c, z, h, b) in enumerate(SITES)
    ]


def approval(id, code, channels, lo, hi, rank, clock, **extra):
    return dict(
        id=id,
        code=code,
        channels=channels,
        start=lo,
        end=hi,
        rank=rank,
        clock=clock,
        basis="utc",
        shift_days=0,
        **extra,
    )


def batch(t):
    if t == 2:
        return [
            approval("B-611", "Q29", "B", "2026-01-01", "2026-12-31", 2, "16:30"),
            approval("Z-213", "U56", "CD", DAYS[1], DAYS[3], 2, "09:15"),
        ]
    if t == 6:
        move = approval("V-57", "N84", "ABCD", DAYS[2], DAYS[2], 4, "09:45")
        move.update(basis="wall", shift_days=-1)
        return [
            approval("T-72", "Q29", "ABCD", DAYS[1], DAYS[2], 5, "17:00"),
            move,
            approval("Z-87", "U56", "BD", DAYS[2], DAYS[3], 3, "10:45"),
            approval("X-34", "J31", "AC", DAYS[1], DAYS[1], 1, "07:10"),
        ]
    if t == 7:
        return [
            dict(id="W-11", target="T-72", channels="BCD", start=DAYS[2], end=DAYS[2]),
            dict(id="W-12", target="Z-87", channels="D", start=DAYS[3], end=DAYS[3]),
        ]
    if t == 9:
        return [
            approval("A-80", "N84", "BD", LATE[1], LATE[2], 3, "13:30"),
            approval("A-81", "J31", "C", LATE[0], LATE[3], 4, "11:40"),
            approval("A-82", "N84", "B", DAYS[2], DAYS[2], 7, "12:50"),
        ]
    return []


def identities():
    return {
        s["code"]: {c: (s["code"] if c in "AD" else s["sid"]) for c in CHANNELS}
        for s in specs()
    }


def queries():
    return [
        dict(channel=c, code=code, day=day, asof=t)
        for t in (4, 6, 7, 8, 9)
        for c in CHANNELS
        for code, day in [
            ("Q29", DAYS[2]),
            ("U56", DAYS[3]),
            ("N84", LATE[2]),
            ("N84", DAYS[2]),
        ]
    ]


def setup(work):
    for name in ("input", *WRITABLE):
        (work / name).mkdir(parents=True, exist_ok=True)
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError("legacy release differs")
    inp_legacy = work / "input" / "previous-release"
    with tarfile.open(ARCHIVE) as old:
        for m in old:
            p = Path(m.name)
            if not m.isfile() or ".." in p.parts:
                continue
            if p.parts[:1] == ("work",) and "__pycache__" not in p.parts:
                active = p.parts[1] in ("project", "input", "data", "scratch")
                dest = (work if active else inp_legacy) / Path(*p.parts[1:])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(old.extractfile(m).read())
    inp = work / "input"
    (inp / "desk.md").write_text(GUIDE)
    (inp / "contracts").mkdir()
    # Regional release and support archive, with joins from contract to event to receipt.
    for y in (2024, 2025):
        for week in range(1, 53):
            folder = inp / "regional" / str(y) / f"week-{week:02}"
            folder.mkdir(parents=True)
            with (
                (folder / "events.csv").open("w") as ev,
                (folder / "delivery.csv").open("w") as dl,
            ):
                a, b = csv.writer(ev), csv.writer(dl)
                a.writerow(("id", "customer", "service_day", "ticket"))
                b.writerow(("receipt", "event", "channel", "result"))
                for i in range(64):
                    code, _, _, _ = SITES[i % 4]
                    day = date.fromisocalendar(y, week, (i % 7) + 1)
                    uid = f"{code}-{day:%Y%m%d}-{i:02}"
                    a.writerow((uid, f"site-{i % 19}", day, f"REG-{y}-{week:02}"))
                    for ch in CHANNELS:
                        b.writerow(
                            (
                                f"{y}-{week}-{i}-{ch}",
                                uid,
                                ch,
                                "accepted" if (i + week) % 17 else "deferred",
                            )
                        )
            write(
                folder / "signoff.json",
                dict(
                    id=f"REG-{y}-{week:02}",
                    state="expired",
                    week=week,
                    owner=f"region-{week % 8}",
                    closed=True,
                ),
            )
    (inp / "contracts/paging.md").write_text(
        "旧 V1 增设 GET /api/pages?channel=A&from=DATE&to=DATE&offset=N&limit=N，返回 {items:[旧 API 行],next:下一偏移整数或 null}。按原始服务日范围内全部 UID 字典序分页，含 legacy 项；不可因单系列 >1000 场静默丢失。维持 /api/events 和 /invite/...。"
    )


def release(run, t):
    inp = run / "work/input"
    (inp / "version.txt").write_text(str(t))
    contract = inp / "contracts"
    if t == 2:
        write(inp / "portfolio.json", specs())
        (contract / "engine.md").write_text(
            """新产品线独立于旧试点。python3 project/line.py import INPUT_DIR 增量导入 portfolio.json 与 INPUT_DIR/orders/*.json（文件含 version,rows）；写 PORTAL_DB。批次可乱序、重送；同一不可变 id 只登记一次。python3 project/line.py query CHANNEL FROM TO ASOF 输出 JSON 数组，每行为 code,day,utc（带时区时间）；按原始周一服务日含端点。只用 version<=ASOF 的已登记授权；普通批准按 code/频道/原定日匹配，取最大 (rank,version,id)，无批准沿用基础。撤回按 target、频道与原定日排除原批准，回退到剩余有效层，不追溯改写旧 ASOF。clock 为 UTC 或场馆当地钟点，由 basis 决定；shift_days 先移原定日再定时刻。未给窗的基础周排期自 2026-03-02 开始。新编号和重复导入用相同入口。"""
        )
    if batch(t):
        write(inp / f"orders/ops-{t}.json", dict(version=t, rows=batch(t)))
    if t == 3:
        write(inp / "identities.json", identities())
        (contract / "interfaces.md").write_text(
            """再次 import 时迁移 identities.json，按 code/channel 查 wire 前缀，UID=前缀-原始服务日YYYYMMDD。提供 /api/v2?channel=C&from=DATE&to=DATE&asof=N，JSON 行含 code,day,utc,uid；旧 API 共存。project/line.py feed CHANNEL FROM TO ASOF OUTPUT 生成全量 VEVENT（CONFIRMED）。同 UID 单场更新而非增生。服务运行时不依赖 input。"""
        )
    if t == 4 or t == 9:
        write(
            inp / "release-window.json",
            dict(days=DAYS if t == 4 else LATE, channels=list(CHANNELS)),
        )
    if t == 5:
        write(
            inp / "support.json",
            [dict(channel=c, code="Q29", day=DAYS[2], asof=4) for c in CHANNELS],
        )
        (contract / "support.md").write_text(
            "project/line.py preview REQUEST_JSON OUTPUT；输出与输入一一对应的对象数组，保留全部查询键，另含 local=Europe/London 的 YYYY-MM-DD HH:MM。实际交 out/preview.json。"
        )
    if t == 7:
        (contract / "delivery.md").write_text(
            "project/line.py delta CHANNEL FROM TO ASOF RECEIPTS_JSON OUTPUT；回执为合并后的批次数组，按 (turn,receipt) 顺序应用 rows 字典（UID→{uid,utc,status}）。只输出新项或相对已应用状态发生变化的事件，空包合法但不投递。out/plan-A.ics 等按三月范围和 ASOF 7。"
        )
    if t == 8:
        (contract / "incident.md").write_text(
            "interruption.json 中每个频道的目标项已尝试单项批次，原 key 为 channel-resume-08（channel 替换为字母）。查真实收件后再决定是否原 key 补发该单项；其他差量另组批次。"
        )
        from .receiver import fault

        fault(run)
    if t == 10:
        write(inp / "questions.json", queries())
        (contract / "inquiry.md").write_text(
            """project/line.py history QUESTIONS_JSON RECEIPTS_BY_CHANNEL_JSON OUTPUT。第二参数为频道→含归档在内的批次数组。逐问题保留 channel,code,day,asof，另含 due 和 received（UTC ISO8601，实收无历史为 null），pending 是两者时刻不一致。due 依当时已知有效政策，received 只取 turn<=asof 的实际已接收版本。实际交 out/inquiry.json。不得重发。"""
        )
    return PROMPTS[t - 1]
