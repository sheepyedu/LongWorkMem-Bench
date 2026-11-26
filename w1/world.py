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


def _june(root):
    data = root / "input"
    _archive(root)
    _office_files(root)
    orders, receipts, invoices = [], [], []
    for index, number in enumerate(range(215, 233)):
        po = f"PO-{number}"
        project = _PROJECTS[(number - 217) % 3]
        for line in range(1, (2 if number % 3 == 1 else 1) + 1):
            # Amounts here are integral cents; store the ERP display value in CNY.
            ordered = 20 + 2 * ((number + line) % 11)
            cents = 1025 + 75 * ((number * line) % 13)
            if (po, line) == ("PO-217", 1):
                ordered, cents = 100, 10000
                batches = [60, 35]
            elif (po, line) == ("PO-215", 1):
                # Two separately signed receipts with the same quantity.
                batches = [ordered // 2, ordered // 2]
            elif (po, line) in {("PO-220", 1), ("PO-219", 1)}:
                batches = [ordered - 4]
            else:
                batches = [ordered - 8, 8]
            orders.append((po, str(line), project, ordered, f"{cents // 100}.{cents % 100:02}"))
            for batch, qty in enumerate(batches, 1):
                receipts.append((f"W{number}-{line}-{batch}", po, line, f"2025-06-{6 + index:02}", qty))
            invoice_qty = ordered - 4 if (po, line) == ("PO-219", 1) else ordered
            invoice_parts = [invoice_qty - 6, 6] if number % 4 == 1 else [invoice_qty]
            for part, qty in enumerate(invoice_parts, 1):
                amount = cents * qty
                if (po, line, part) == ("PO-222", 1, 1):
                    amount += 350
                invoices.append((f"V{number}-{line}-{part}", po, line, qty,
                                 f"{amount // 100}.{amount % 100:02}"))
    receipts += [receipts[0], ("W-MIG-39", "PO-193", 9, "2025-06-25", 3)]
    invoices.append(("V-MIG-54", "PO-208", 8, 2, "76.00"))
    _csv(data / "orders.csv", "po,line,project,ordered,unit_price", orders)
    _csv(data / "receipts_june.csv", "event,po,line,date,qty", receipts)
    _csv(data / "invoices.csv", "invoice_line,po,line,qty,amount", invoices)
    _text(data / "关账口径.txt", """
松岚设备｜采购与仓储月结口径，财务部 2025 年 6 月修订。
本期底账取 input/orders.csv、本期发票文件 input/invoices*.csv 及陆续到件的 input/receipts_*.csv。archive 为已办账期存档。
采购行由 po 与 line 共同标识。同一采购行可有多个收货事件、发票行。分别归集后再对采购订单。发票行按 invoice_line 去重，红字调整金额为负。
同一仓储事件 event 重复导出只入账一次；单号不同的等量签收分别入账。qty 带符号，退库为负。
以仓库过账日期 date 截止统计。无匹配采购行的发票或仓储事件列入待认领，不得并入任何采购行。按各自业务编号去重。
每一采购行均需列账。无收货或发票的相应合计记 0。invoiced_qty、invoiced_amount 为逐行开票数量、含税金额合计。
qty_diff = 净入库数量 net 减订货数量 ordered；amount_diff = 开票金额合计减净入库数量乘订单含税单价。
数量差非零记 Q，金额差非零记 A，两者兼有记 QA，无差异留空。各类可重叠，异常行总数按采购行去重。
CSV 首行保留指定英文栏名，UTF-8 逗号分隔；数量整数，金额单位人民币元，保留两位小数，不加千分位。
""")
    _mail(root, "HR-0618", "2025-06-18", "pm", "借调申请 HR-46｜请人事审批",
          "拟将 E07 的共享支援工时由甲项目转入乙项目。建议 2025-06-01 起执行。申请日期不作批准日期，候人事正式批复。")
    _mail(root, "AP-0627", "2025-06-27", "ap", "六月到票清单已上传",
          "本次发票以发票行登记，部分供应商分次开具。历史目录保留了旧清单，请从本期台账核对。")
    _mail(root, "WH-0627", "2025-06-27", "warehouse", "六月首批仓库导出",
          "近期盘点导致部分业务行重复落在导出分页中。过账时请以仓储事件编号识别原凭证。")


def _amend(root, variant):
    _csv(root / "input" / "receipts_amend.csv", "event,po,line,date,qty", [
        ("W217-1-2", "PO-217", 1, "2025-06-08", 35),
        ("W-RT-630", "PO-217", 1, "2025-06-30", -5),
        ("W-MIG-39", "PO-193", 9, "2025-06-25", 3),
    ])
    _mail(root, "WH-0630", "2025-06-30", "warehouse", "退库补录｜六月关账前请查收",
          "检验复核后已登记退库。补送文件沿用了上次导出的一部分业务行，请在六月结账前并回。")
    effective = {"A": "2025-07-01", "B": "2025-08-01"}[variant]
    _mail(root, "HR-0628", "2025-06-28", "hr", "人事批复 HR-46｜共享支援工时归属",
          f"员工号：E07\n批准事项：共享支援工时由甲项目转归乙项目。\n批准生效日：{effective}\n"
          "生效日前的共享工时仍归甲；已写明项目的工时保持原登记。人事部签发，财务以此办理。")


def _july(root):
    _csv(root / "input" / "receipts_july.csv", "event,po,line,date,qty", [
        ("W-J701", "PO-217", 1, "2025-07-03", 10),
        ("W-J702", "PO-220", 1, "2025-07-08", 4),
        ("W-J703", "PO-219", 1, "2025-07-08", 4),
    ])
    _csv(root / "input" / "invoices_july.csv", "invoice_line,po,line,qty,amount", [
        ("V-J724", "PO-219", 1, 4, "74.00"),
        ("V-J736", "PO-222", 1, 0, "-3.50"),
    ])
    _mail(root, "AP-0708", "2025-07-08", "ap", "七月补开及红字调整已登记",
          "PO-219 的尾批发票已到。PO-222 收到不涉及数量的价款调整，供应商已开红字。两行均归七月。")
    _mail(root, "WH-0708", "2025-07-08", "warehouse", "七月到货已过账",
          "补货的仓储事件已经过账。六月已报数字按当时截点保留，七月另行更新当前账。")


def _releases(root):
    _csv(root / "input" / "releases.csv", "project,status,pool", [
        ("甲", "已放行", "10000.01"), ("乙", "已放行", "6070.17"), ("丙", "待批", "3000.00"),
    ])
    _mail(root, "FN-0730", "2025-07-30", "finance", "七月项目结算批复 F-72",
          "甲、乙两项准予结算，具体奖金池以随文的 releases.csv 登记为准。丙的结项会签还缺签字，继续暂缓。")


def _hours(root):
    _csv(root / "input" / "hours.csv", "employee,project,hours", [
        ("E01", "甲", 6), ("E02", "甲", 10), ("E01", "甲", 4), ("E03", "甲", 7),
        ("E07", "甲", 2), ("E04", "乙", 8), ("E05", "乙", 9), ("E06", "乙", 5),
        ("E07", "乙", 3), ("E07", "共享", 1), ("E08", "丙", 10), ("E02", "丙", 4),
    ])
    _text(root / "input" / "奖金分配办法.txt", """
七月项目奖金按核准工时发放。hours.csv 表内所有工时均发生在 2025-07-15。
有明确项目的工时按所记项目入账。共享工时依人事签发的生效批件在实际工时日认定项目。
同一员工同项目多条工时须合计。仅列入已获放行项目中工时为正的员工。
以项目为单位用奖金池乘个人工时占比，先逐人向下截到分。整笔剩余分币全部给本项目合计工时最高的人。
若最高工时并列，给员工号按字符升序最小的一人。每个项目的应发合计应与获批奖金池一致。
""")


def _distribution(root):
    _csv(root / "input" / "分发清册.csv", "recipient,attachment,scope", [
        ("finance@office.test", "out/pay.csv", "财务：七月获批项目逐人金额及工时"),
        ("jia@office.test", "out/jia.csv", "甲项目负责人：仅甲项目七月合计"),
        ("yi@office.test", "out/yi.csv", "乙项目负责人：仅乙项目七月合计"),
    ])
    _mail(root, "FN-0731", "2025-07-31", "finance", "七月奖金发放包请先呈核",
          "负责人仅阅各自项目汇总。请分别拟稿，等发放通知后另行投递，勿抄送。")


_PROMPTS = (
    """我们要做松岚设备六月采购关账。请用本期采购、开票和仓储底账，按 2025-06-30 截点先出一份逐行对账底表和待认领清单。口径在 input/关账口径.txt。
交 out/current.csv，栏名为 po,line,project,ordered,net,invoiced_qty,invoiced_amount,qty_diff,amount_diff,flags。
交 out/orphans.csv，栏名 source,id,po,line。source 用 receipt 或 invoice，id 填原事件号或发票行号，无待认领也留表头。
这是本地办公室工作区。可查询 input/ 和 inbox/，用文件工具、Python、openpyxl 整理账表，可自行留笔记。各轮正式交付放 out/，邮件用办公室本地邮箱。""",
    """仓库今天补了一份六月导出，内有退库，请按账务口径与原明细合并，把六月底表和待认领清单更新到同一位置。办公室来件也已同步到收件箱，请把需要留待后续办理的事项一并留存。""",
    """财务确认六月关账。请把目前的六月底表原样归档到 out/frozen/2025-06.csv，将这份已报送版本冻结，仍保留 out/current.csv 处理后续来件。以后更新当前账时不要改写归档。""",
    """先放一下台账维护，周会现在需要六月例外简报。依已报送版本给出 out/brief.csv（po,line,flags,qty_diff,amount_diff，每条有差异的采购行列一次），以及 out/meeting.csv（一行，total_lines,exception_lines,qty_lines,amount_lines,orphan_events）。列明采购行总数、去重异常行数、数量及金额各类异常行数，并单列待认领的独立流水/发票行总数。""",
    """接回原来的采购账。七月实际过账的补收入库单和应付组的补票、红字调整均已到齐，按 2025-07-08 截点更新 out/current.csv 和 out/orphans.csv。六月已报送版仍要能原样调阅。""",
    """财务转来了本月结算批复。请结合当前账更新可办理的项目清单，按书面放行范围列出 out/released.csv（project,pool），暂缓项目留待下一批。""",
    """办理七月项目奖。请按已批项目、核准工时、有效人员归属和奖金分配办法出逐人清单 out/pay.csv（project,employee,hours,bonus，仅列有核准工时的项目员工组合）。
财务还要一份可改数重算的 out/bonus.xlsx。Pools 页的前两栏为 project,pool，每个已批项目一行；Pay 页的前四栏为 project,employee,hours,bonus，每个项目员工组合一行。改 Pools 的奖金池或 Pay 的一人工时后，Pay 的奖金公式都须按办法自动重算，项目总额须守恒。可用辅助列或辅助页。金额以元记录到分。""",
    """请把七月奖金材料按新到的分发清册分头准备。财务附件沿用 out/pay.csv；各项目负责人只看自己项目的合计，各一行，out/jia.csv 和 out/yi.csv 的栏名均为 project,period,hours,bonus，period 填 2025-07。
请在本地邮箱用 draft 分别建立三封草稿，每封一个收件人、一份对应附件、写明事由的主题。草稿待财务确认后再发送。""",
    """财务已核准发放。请按上一步核对的三封草稿，用本地邮箱 deliver 分别投递一次，保持收件人、附件及主题一致。按实际投递回执登记 out/receipts.csv（recipient,receipt,attachment，attachment 填含 out/ 的工作区相对路径）。保留六月冻结版、本期可重算奖金工作簿和已发附件备查。""",
)


def release(workspace: Path, turn: int, variant: str) -> str:
    """Publish a single turn's materials, returning the corresponding office request."""
    if turn not in range(1, len(_PROMPTS) + 1):
        raise ValueError(f"Unknown turn: {turn!r}")
    if variant not in ("A", "B"):
        raise ValueError(f"Unknown variant: {variant!r}")
    root = Path(workspace)
    for directory in ("input", "inbox", "out"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    if turn == 2:
        _amend(root, variant)
    else:
        stage = {1: _june, 5: _july, 6: _releases, 7: _hours, 8: _distribution}.get(turn)
        if stage:
            stage(root)
    return _PROMPTS[turn - 1]
