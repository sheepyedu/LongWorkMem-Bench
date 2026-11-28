"""Customer migration desk. Only files released by setup/issue are participant-visible."""

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from tasks.c1.runstate import freeze
from tasks.c2.evolution import scenario as legacy
from tasks.c2.evolution.receiver import archive
from tasks.c2.scenario import write
from tasks.c2.subscriber import accept, receipts

CHANNELS = legacy.CHANNELS
VERSION = "calendar-cohorts-v2"
MATERIAL_REVISION = "registrations-1"
SCORING_REVISION = VERSION + "/atoms-1"
DAYS = ("2026-03-02", "2026-03-09")
CODES = ("Q29", "N84")
ANNEX = "regional/2025/week-42/renewal.json"
CUT = "2026-02-01T00:00:00Z"
PROMPTS = [
    legacy.PROMPTS[0],
    "接手四个客户邮箱的春季课程。接入班表、报名记录与生效附件，并实现可重送的数据库导入与查询。当前工单见 input/ticket.md。",
    "合作方更换订阅标识。按报名时间迁移，保住既有邀请与报名。让同一业务频道内两代客户可以同时工作。",
    "把两个服务日的全部邀请首发给四位客户，用真实回执核对结果。",
    "客服要逐人确认第二个服务日的邀请和伦敦时间。交付只读预览。",
    "第二周临时改时。导入新批复，按实际签收差量通知客户，保留第一周与未涉及课程。",
    "委员会只撤回部分客户的临时批准。回退到原合同，备好四个待发包，暂缓发送。",
    "队列出现超时。核对订阅端，处理已放行客户；冻结客户留到交接时处理。值班记录见本轮工单。",
    "数据库已从第七轮恢复，订阅端没有回滚。接管旧邀请、重查回执、解除冻结并补齐缺件，交可冷启的备份。",
    "客户质疑此前通知。请按当时授权与当时真实签收逐笔答复，交可复跑的追溯程序。",
]


def registrations():
    rows = []
    for i, a in enumerate(CHANNELS):
        for j, code in enumerate(CODES):
            old = (i + j) % 2 == 0
            rows.append(
                dict(
                    account=a,
                    channel="north" if i < 2 else "south",
                    code=code,
                    joined="2026-01-31T18:59:59-05:00"
                    if old
                    else "2026-02-01T01:00:00+01:00",
                    old_prefix=f"invite-{a.lower()}-{j + 31}",
                    booking=f"BK-{821 + i * 2 + j}",
                )
            )
    return rows


def shifts(t):
    if t == 6:
        return [
            dict(
                id="T-260",
                code="Q29",
                day=DAYS[1],
                accounts=list(CHANNELS),
                utc_clock="18:00",
            )
        ]
    if t == 7:
        return [dict(id="W-264", target="T-260", day=DAYS[1], accounts=["B", "C", "D"])]
    return []


def questions():
    return [
        dict(account=a, code=c, day=DAYS[1], asof=v)
        for v in (4, 6, 7, 8, 9)
        for a in CHANNELS
        for c in CODES
    ]


def setup(work):
    legacy.setup(work)
    inp = work / "input"
    # Four existing, real R1 invites predate the long paging sample.
    with sqlite3.connect(work / "data/portal.sqlite") as db:
        for r in registrations():
            if datetime.fromisoformat(r["joined"]) < datetime.fromisoformat(CUT):
                uid = r["old_prefix"] + "-20260302"
                clock = (
                    {"A": "14:05", "C": "16:15"}[r["account"]]
                    if r["code"] == "Q29"
                    else "14:45"
                )
                db.execute(
                    "insert into events(uid,starts) values(?,?)",
                    (uid, DAYS[0] + "T" + clock + ":00Z"),
                )
                db.execute(
                    "insert into bookings(id,uid) values(?,?)", (r["booking"], uid)
                )
    (inp / "desk.md").write_text(
        "维护跨时区邀请门户。每轮读 input/ticket.md。project、data、out、notes、scratch 跨委托持久；input 只读。离线 Python 3.12，SQLite 用标准库。publish(channel,key,file) 的 channel 是客户邮箱 A/B/C/D；file 须为 out/ 下的 ICS。handover- 前缀由收件系统为超时项签发，签发前不可占用。每个新 key 产生客户通知，相同 key 加相同事件重送幂等。receipts(channel) 是在线真实签收，第五轮起早期批次可由 input/vault/index.json 取回。旧试点归档不是本产品授权。"
    )
    (inp / "ticket.md").write_text("旧门户分页合同见 contracts/paging.md。")
    write(
        inp / ANNEX,
        dict(
            id="RN-42",
            status="signed",
            utc_by_account={"A": "14:05", "B": "15:10", "C": "16:15", "D": "17:20"},
        ),
    )
    write(
        inp / "regional/2025/week-41/renewal.json",
        dict(
            id="RN-41", status="expired", utc_by_account={a: "10:00" for a in CHANNELS}
        ),
    )


def inject(run):
    # Commit of exactly one pending item is independent of any agent report.
    pending = []
    for account, prefix, clock in (
        ("C", "invite-c-31", "16:15"),
        ("D", "s-q", "17:20"),
    ):
        uid = prefix + "-20260309"
        row = dict(uid=uid, utc=DAYS[1] + "T" + clock + ":00Z", status="CONFIRMED")
        key = f"handover-{account}-Q29"
        pending.append(
            dict(account=account, uid=uid, key=key, transport="timeout", utc=row["utc"])
        )
        if account == "C":
            accept(run, 8, account, key, {uid: row}, CHANNELS)
    write(run / "work/input/timeouts.json", pending)


def issue(run, t):
    work = run / "work"
    inp = work / "input"
    (inp / "version.txt").write_text(str(t))
    if t == 1:
        return PROMPTS[0]
    if t == 2:
        write(inp / "roster.json", registrations())
        write(
            inp / "schedule.json",
            dict(
                days=DAYS,
                classes={
                    "Q29": dict(basis="signed-annex", ref=ANNEX, approval="RN-42"),
                    "N84": dict(basis="wall", zone="America/New_York", clock="09:45"),
                },
            ),
        )
        (inp / "contracts/service.md").write_text(
            """python3 project/service.py import DIR 把 DIR/schedule.json、roster.json 和已到达的 migration.json、orders/*.json 增量登记到 PORTAL_DB（默认 data/portal.sqlite）。重送同一来件无副作用；历史截止用逻辑版本号。附件路径相对 DIR，只有班表所引签署且编号匹配的附件有效。Q29 采用附件为该客户规定的 UTC 钟点，N84 采用场馆当地钟点。python3 project/service.py view ACCOUNT ASOF 将所有业务行打印为 JSON 数组。每行含 account,code,day,booking,uid,utc；day 是原定业务日，utc 须带偏移，UID=前缀-YYYYMMDD。迁移前沿用报名 old_prefix。发布件为 CONFIRMED 的 ICS。运行 view、delta、history 时只依赖库及其显式参数。报名及旧试点仍有效。"""
        )
    if t == 3:
        write(
            inp / "migration.json",
            dict(
                version=3,
                cutover=CUT,
                prefixes={
                    "north": {"Q29": "n-q", "N84": "n-n"},
                    "south": {"Q29": "s-q", "N84": "s-n"},
                },
            ),
        )
        (inp / "contracts/identity.md").write_text(
            "从版本 3 起逐条报名将 joined 与 cutover 转为绝对时刻比较。严格早于切点的报名终身沿用 old_prefix，其余采用业务频道和课程对应的新前缀，保留同一 booking。旧客户端继续通过 bookings(id,uid) 和 /invite/<uid>?tz=UTC 读取已登记的第一周邀请。邮箱各自独立；客户端以 UID 更新现有邀请，改 UID 会新增活动。"
        )
    if t == 5:
        archive(run)
        write(
            inp / "support.json",
            [dict(account=a, code="N84", day=DAYS[1], asof=4) for a in CHANNELS],
        )
    if shifts(t):
        write(inp / f"orders/{t}.json", dict(version=t, rows=shifts(t)))
    if t == 8:
        disk = work / "data"
        if disk.is_symlink():
            raise ValueError("invalid recovery disk")
        with tempfile.NamedTemporaryFile(dir=disk, mode="w", delete=False) as temp:
            json.dump({a: receipts(run, a, CHANNELS) for a in CHANNELS}, temp)
        Path(temp.name).replace(disk / "receipt-cache.json")
        freeze(work / "data", run / "restore-point")
        inject(run)
    if t == 9:
        # Restore only the simulated database disk; recipient journals are host-owned.
        restore = run / "restore-point"
        if not restore.is_dir():
            raise RuntimeError("missing R7 recovery point")
        # Copy from inside the same Docker mount used by the program. Host-side
        # replacement can leave stale inodes visible to SQLite on shared VM disks.
        from tasks.c2.pilot import execute

        stage = inp / "repair-disk"
        freeze(restore, stage)
        manifest = run / "manifest.json"
        image = (
            json.loads(manifest.read_bytes())["image"]
            if manifest.exists()
            else "longworkmem-calendar:1"
        )
        cmd = """python3 - <<'RESTORE'
import shutil
from pathlib import Path
disk=Path("data")
for item in disk.iterdir():
    if item.is_symlink() or not item.is_dir():item.unlink()
    else:shutil.rmtree(item)
for item in Path("input/repair-disk").iterdir():
    dest=disk/item.name
    if item.is_symlink():dest.symlink_to(item.readlink())
    elif item.is_dir():shutil.copytree(item,dest,symlinks=True)
    else:shutil.copy2(item,dest)
RESTORE"""
        result = execute(work, cmd, image)
        if result["status"]:
            raise RuntimeError(
                "recovery disk transfer failed: " + result["output"][-300:]
            )
    if t == 10:
        write(inp / "questions.json", questions())
    tickets = {
        2: "contracts/service.md、schedule.json 和 roster.json。请在现有 SQLite 库上线。",
        3: "migration.json、contracts/identity.md。重送导入，继续支持旧版本查询。",
        4: "首发 schedule.json 的全部课程、日期给每个邮箱。每个账户单独成包。",
        5: "input/support.json 的问题逐笔输出到 out/preview.json 数组。保留查询键，另含 uid、local（伦敦 YYYY-MM-DD HH:MM）。不要发布。",
        6: "orders/6.json 为最新签发的临时 UTC 钟点；按账户、课程、原定日匹配。仅发有变化的邀请。",
        7: "orders/7.json 只在所列日期及账户撤回 target，回退到仍有效的合同。project/service.py delta ACCOUNT ASOF RECEIPTS_JSON OUTPUT 产生 ICS：将传入批次按 (turn,receipt) 顺序应用 rows 字典，截止 ASOF；仅输出应有且实收缺少或时间/状态不同的邀请。空包合法，不发送。四端分别交 out/plan-A.ics 等。",
        8: "timeouts.json 两笔单项均收到传输超时，服务端是否签收应向真实端核对。仅放行 A、B；C、D 冻结至下轮，禁止产生新通知。缺少的超时项解冻后用原 key 单独重试。data/receipt-cache.json 是故障前镜像。其余缺件可另行组包。",
        9: "input/repair-disk 是第七轮只读恢复介质，data 已实际还原为 R7 收盘状态，所有客户现已解冻。归档加在线回执是实收依据。按上轮恢复约定补发并再次核对。交 out/backup.sqlite；只带 project 和该库亦须能查询各历史版本和计算差量。",
        10: "project/service.py history QUESTIONS_JSON LEDGER_JSON OUTPUT。LEDGER_JSON 为邮箱→批次数组（含归档）。按 (turn,receipt) 合并至各题 asof；输出数组保留查询键，另含 uid,due,received,pending。received 无签收为 null，pending 是应发与实收时刻不一致。交 out/inquiry.json，只读。",
    }
    (inp / "ticket.md").write_text(tickets[t])
    return PROMPTS[t - 1]
