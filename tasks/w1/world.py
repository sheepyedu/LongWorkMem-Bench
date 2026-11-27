"""Material releases for the synthetic 松岚设备 procurement and payroll office."""

import csv
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path


def _text(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def _csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(columns.split(","))
        writer.writerows(rows)


def _mail(root, filing_id, day, sender, subject, body):
    message = EmailMessage(policy=policy.SMTPUTF8)
    message["From"] = f"{sender}@office.test"
    message["To"] = "operations@office.test"
    sent = datetime.fromisoformat(day).replace(hour=9, minute=30, tzinfo=timezone(timedelta(hours=8)))
    message["Date"] = format_datetime(sent)
    message["Message-ID"] = f"<{filing_id}@office.test>"
    message["Subject"] = subject
    message.set_content(body.strip() + "\n", charset="utf-8", cte="8bit")
    (root / "inbox" / f"{filing_id}.eml").write_bytes(message.as_bytes())


_PROJECTS = ("甲", "乙", "丙")
_PRODUCTS = ("中间继电器", "光电传感器", "端子排", "线槽盖板", "防水护套", "温度探头", "控制面板", "安装角码")


def _archive(root):
    """Closed prior periods retained by purchasing, the warehouse and finance."""
    archive = root / "input" / "archive"
    for month in range(1, 6):
        period = f"2025-{month:02}"
        contacts = []
        for idx, project in enumerate(_PROJECTS):
            project_dir = archive / period / f"{project}项目"
            name = ("嘉港配件", "南亭机电", "林泽材料")[idx]
            lines, receipts, invoice_rows = [], [], []
            for item in range(1, 6):
                po = f"PO-{100 + month * 11 + idx * 3 + item // 2}"
                line = item % 2 + 1
                qty = 12 + item * 3 + month
                price = 15 + 2 * idx + item
                sku = _PRODUCTS[(month + idx + item) % len(_PRODUCTS)]
                lines.append((po, line, sku, qty, f"{price}.00"))
                receipts.append((f"{month:02}-R{idx}{item}", po, line, qty, f"{period}-20"))
                invoice_rows.append((f"{month:02}-V{idx}{item}", po, line, qty, f"{qty * price}.00"))
            _csv(project_dir / "订货存根.csv", "po,line,item,ordered,unit_price", lines)
            _csv(project_dir / "签收明细.csv", "event,po,line,qty,date", receipts)
            _csv(project_dir / "开票登记.csv", "invoice_line,po,line,qty,amount", invoice_rows)
            _text(project_dir / "移交单.txt",
                  f"{period} {project}项目月结材料移交单\n供方：{name}\n采购跟单：{('陈蔚','徐荷','林望')[idx]}\n"
                  f"收货登记 {len(receipts)} 行，签收原件留仓库，电子登记交财务留存。")
            contacts.append((project, name, ("陈蔚", "徐荷", "林望")[idx]))
            correspondence = (
                ("buying", "请确认采购交期", f"{name}已回签当月订货单，首批{lines[0][2]}拟于本月中旬送达。"),
                ("warehouse", "签收安排", f"到货有两箱分拣件，请按订单 {lines[0][0]} 的行号分别点收。"),
                ("ap", "发票抬头核对", f"{name}开票资料核准，发票号码与采购行的对应表见当月开票登记。"),
                ("ops", "月末资料移交", f"本月共 {len(lines)} 行采购材料已入档，移交记录与签收明细同存。"),
                ("admin", "仓库盘点值班", f"{project}项目货位由{contacts[-1][-1]}协助点数，备品另盘。"),
                ("finance", "旧账期结案", f"附件已按 {period} 归档，后续来票请写明采购单及行号。"),
                ("pm", "下月备件需求", f"检修准备会提出补充{lines[-1][2]}，数量待仓库清点后再提请购。"),
            )
            for sequence, (sender, subject, body) in enumerate(correspondence, 1):
                _mail(root, f"M{month:02}-{idx + 1}{sequence}", f"{period}-{10 + sequence:02}",
                      sender, f"{period} {project}项目 | {subject}", body)
        month_dir = archive / period
        _csv(month_dir / "供应商联系册.csv", "project,supplier,buyer", contacts)
        _csv(month_dir / "pay.csv", "project,employee,hours,bonus",
             [(project, f"E{employee:02}", 8 + employee, f"{240 + month * employee}.00")
              for employee, project in enumerate(_PROJECTS, 1)])
        _text(month_dir / "会议决议.txt",
              f"{period} 例会留存\n各项目负责人已核对已报采购行。仓库将退料记录随签收单保存。")
        _csv(month_dir / "纸档目录.csv", "box,period,project,contents",
             [(f"{month:02}/{idx}", period, project, "采购存根、收货签字联、发票留存联")
              for idx, project in enumerate(_PROJECTS, 1)])


def _office_files(root):
    admin = root / "input" / "综合办公室" / "2025-06"
    _csv(admin / "培训" / "急救课报名.csv", "employee,session,registered", [
        ("E03", "下午", "2025-06-20"), ("E07", "上午", "2025-06-21"), ("E09", "上午", "2025-06-22"),
        ("E03", "下午", "2025-06-23"), ("E12", "下午", "2025-06-24"),
    ])
    _text(admin / "培训" / "六月培训日程.txt", "六月二十七日 急救与现场联络，教室 B204，上午和下午各一场。请携工牌签到。")
    _csv(admin / "总务" / "会议室预约.csv", "room,date,start,end,department", [
        ("B204", "2025-06-27", "09:00", "11:00", "培训"), ("B204", "2025-06-27", "14:00", "16:00", "培训"),
        ("A301", "2025-06-30", "10:00", "11:00", "行政"),
    ])
    _text(admin / "总务" / "临时访客须知.txt", "六月机房维护期间，来访人员在东门签到，由接待部门领取临时通行证。")
    _csv(admin / "信息服务" / "报修台账.csv", "ticket,asset,opened,issue,status", [
        ("IT-125", "PR-03", "2025-06-25", "进纸轮卡纸", "已换件"), ("IT-127", "SC-02", "2025-06-26", "玻璃条污渍", "待清洁"),
    ])
    _csv(admin / "信息服务" / "耗材领用.csv", "date,item,count,asset", [
        ("2025-06-18", "黑色墨粉", 1, "PR-01"), ("2025-06-25", "进纸轮", 1, "PR-03"),
    ])
    _csv(admin / "值班" / "前台轮值.csv", "date,morning,afternoon", [
        ("2025-06-26", "邓青", "范蕾"), ("2025-06-27", "夏帆", "高泉"), ("2025-06-30", "范蕾", "邓青"),
    ])
    _text(admin / "值班" / "交接事项.txt", "六月三十日早班领取新一批访客证，晚班点清归还数量并交回东门传达室。")
    _csv(root / "input/archive/2025-05/甲项目/jia.csv", "project,period,hours,bonus",
         [("甲", "2025-05", 9, "245.00")])
    _mail(root, "TR-0626", "2025-06-26", "training", "明日急救培训签到安排",
          "B204 有上午和下午两场，按综合办公室六月培训日程到场，已报名者携工牌。")
    _mail(root, "IT-0627", "2025-06-27", "it", "三楼打印机可以使用了",
          "PR-03 卡纸的进纸轮已经更换，使用费用登记在本月耗材领用表。")
    _mail(root, "AD-0625", "2025-06-25", "admin", "本周访客接待轮值更新",
          "周四、周五的早晚班见最新前台轮值表，本周临时通行证仍从东门领取。")
    _mail(root, "FM-0624", "2025-06-24", "facilities", "会议室门牌更换时间",
          "A301 门牌周五下班后更换，周一上午的预约照常。")
