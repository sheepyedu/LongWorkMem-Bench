"""Issue the public work orders. Future approvals live outside the engineering desk."""
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import sqlite3

from tasks.c1.sandbox import WRITABLE

START = "2026-03-06"
SERIES = [dict(code="K17",anchor="2026-03-06T15:00:00Z",zone="America/New_York",order="OP-381"),
          dict(code="M42",anchor="2026-03-06T15:00:00Z",zone="America/New_York",order="OP-629")]
PROMPTS = [
"东京运营报告日期偶尔提前一天。请修复门户列表和邀请详情；既有 UTC API、报名和链接继续可用。先读 input/desk.md。",
"请迁移本次 intake.json 中的两个系列并按各自签批续排，保留已有报名和邀请标识。迁移命令能重复执行；上线后要能用相同入口接收新编号。",
"给伦敦合作方一份 3 月 6 至 27 日的四周试点预览，不要投递。交 out/preview.json，数组每行含 uid、local（伦敦 YYYY-MM-DD HH:MM）。仅列试点。",
"批准首发。把这四周的两个试点系列正式发到 A、B 两个频道；落实可重复运行的发布准备入口并检查真实回执。",
"本周签批 CH-51、CH-53 已到。请实现单场改期和临时窗口，更新两个频道。只推送相对收件历史有变化的场次，保留原邀请身份。",
"B 频道撤回上一批的一部分，请执行 CH-64。A 的批复继续有效，场馆的改期也要保留。请核对实际收件后增量更正。",
"值班台中断了紧急更新，两个频道各有一笔未确认。查 incident.json 和实际收件历史，恢复缺件，避免重复通知。请保存可重用的恢复入口，重启后再运行一次确认无待补。",
"用备份交接门户，在干净实例也能继续工作。交 out/backup.sqlite，发布四月到六月全部试点给 A、B，另在 out/new-A.ics 交新订阅者的第二季度全量文件。旧邀请须可继续定位。"
]
GUIDE="""排期维护工位，业务日由 input/clock.txt 给出。可写 project、data、out、scratch、notes。其他目录只读。Python 3.12 标准库和系统时区库已安装。通过 shell 运行 project/http_read.py URL 可请求实际门户。
旧 API GET /api/events?from=YYYY-MM-DD&to=YYYY-MM-DD&channel=A，返回对象数组，含 uid、utc（带时区 ISO8601）、status。日期范围按原定场次日（含端点）筛选。/ 和 /invite/UID 接收 tz=IANA 和 channel，要求可见文本含当地 YYYY-MM-DD HH:MM。旧报名不可丢。
PORTAL_DB 指定 SQLite 路径，默认 data/portal.sqlite。python3 project/portal.py migrate 从 input/intake.json 读取系列（缺文件时无新增），代码表对应的签批存于资料库。新编号也可引用同一批准；迁移为增量导入，保留此前系列。两个试点每周五一次，无截止；交付按指定区间展开。已部署订阅端按独立 VEVENT UID 匹配：系列代码-原定日，例如 K17-20260306。已有系列首场与同 UID 的旧活动合并，旧报名不变。非试点继续提供旧接口。为避免客户端重新插入，改期保留原 UID。
发布准备：python3 project/prepare.py CHANNEL FROM TO OUTPUT，输出自包含 ICS，包含所有该频道该区间试点（排除非试点旧活动），空区间也需合法 VCALENDAR。project/calendar_io.py 可用。更新分发只投递需要改变的 VEVENT，状态为 CONFIRMED；频道范围变更也须在门户 API 和发布准备入口生效，频道独立，每实际接收一次均通知；更换 key 重发相同内容也会通知。用 publish(channel,key,file) 发送 out 下的文件（路径相对工位），receipts(channel) 返回真实已接收批次、去重键和各场次。相同键和语义相同的内容可重试；语义不同禁止复用。没有变化时无需投递。用户要求预览时严禁投递。
恢复入口：python3 project/recover.py INCIDENT RECEIPTS CHANNEL OUTPUT，根据工单和已收回执 JSON 数组生成仅含未送达项的 ICS。空结果不投递。incident.json 含待确认的原始 key、UID、UTC、状态，重发使用原 key。该批补正继续用于门户及历史查询。交接时数据库备份配合 project/ 即可从 PORTAL_DB 干净重启，无需原工位的 notes、input 或 data。"""
def write(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2))


def setup(work):
    for sub in ("input",*WRITABLE):
        (work/sub).mkdir(parents=True,exist_ok=True)
    shutil.copytree(Path(__file__).with_name("starter"),work/"project",dirs_exist_ok=True,ignore=shutil.ignore_patterns("__pycache__"))
    inp=work/"input"
    (inp/"desk.md").write_text(GUIDE)
    # Searchable former approvals and their corresponding actual schedules.
    for i in range(96):
        code=("K17","M42",f"H{i:02}")[i%3]
        start=date(2023+i//48,1,1)+timedelta(days=(i%48)*7)
        name=f"ARC-{i:04}"
        folder=inp/"records"/str(start.year)/name
        folder.mkdir(parents=True)
        (folder/"decision.txt").write_text(f"{name} 批准 | 系列 {code} | 生效 {start} 至 {start+timedelta(days=27)} | 渠道 {'AB'[i%2]} | 临时时移 {(i%5)-2} 小时。到期终止。\n")
        with (folder/"dispatch.csv").open("w") as f:
            wr=csv.writer(f);wr.writerow(["receipt","series","service_day","channel","accepted"])
            for j in range(104):
                wr.writerow([f"{name}-{j}",code,start+timedelta(days=j//4),"AB"[j%2],int(j%11!=0)])
        write(folder/"venue.json",dict(region=["Europe/London","America/New_York","Asia/Tokyo"][i%3],series=code,order=name))
    with sqlite3.connect(work/"data/portal.sqlite") as db:
        db.executescript("create table events(uid text primary key,starts text not null);create table bookings(id text primary key,uid text not null);")
        for uid,utc in [("legacy-east","2026-03-05T23:30:00Z"),("legacy-west","2026-03-06T02:15:00Z")]+[(s["code"]+"-20260306",s["anchor"]) for s in SERIES]:
            db.execute("insert into events values(?,?)",(uid,utc))
            db.execute("insert into bookings values(?,?)",("seat-"+uid,uid))


def release(work,t):
    inp=work/"input"
    (inp/"clock.txt").write_text(["2026-02-18","2026-02-19","2026-02-20","2026-02-21","2026-02-24","2026-02-25","2026-02-26","2026-03-30"][t-1])
    if t==2:
        write(inp/"intake.json",SERIES)
        for s,text in zip(SERIES,["全年保持首场的场馆当地钟点","全年保持首场的 UTC 钟点"]):
            (inp/"records"/(s["order"]+".txt")).write_text(s["order"]+" 正式批准：按合同 "+text+"；适用于引用本工单的系列。")
    if t in (5,6):
        docs={5:{"CH-51":"K17 原定 3月20日 场次提前一日，仍用场馆惯用钟点。A、B 均生效。",
                 "CH-53":"M42 原定 3月13日、20日两场按通常 UTC 时刻推迟两小时，A、B 均生效，到期恢复。"},
              6:{"CH-64":"仅撤销 CH-53 对 B 的 3月20日单场批准，恢复原合同时间。"}}[t]
        for key,value in docs.items():(inp/"records"/(key+".txt")).write_text(value)
    return PROMPTS[t-1]
