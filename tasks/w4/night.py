"""Public business materials for the night service handover (edition 3)."""

from openpyxl import Workbook, load_workbook

from .annex import POOLS, csvfile
from .scenario import FIRST, object_id, put

IDS = tuple(f"H{i:02}" for i in range(1, 13))
# The order of the queue is the published service priority.
QUEUE = (
    "H03",
    "H08",
    "H01",
    "H06",
    "H11",
    "H04",
    "H09",
    "H02",
    "H12",
    "H05",
    "H10",
    "H07",
)
SITE = dict(
    zip(
        IDS,
        (
            POOLS[0],
            POOLS[1],
            POOLS[0],
            POOLS[2],
            POOLS[3],
            POOLS[1],
            POOLS[2],
            POOLS[3],
            POOLS[0],
            POOLS[2],
            POOLS[1],
            POOLS[3],
        ),
    )
)
BASE = dict(zip(IDS, (6, 4, 5, 6, 3, 7, 4, 6, 5, 4, 6, 5)))
# Signed HZ-A and JL-B overrides coexist with non-binding proposals.
AMENDMENTS = [
    (2, "HZ-A", "签发", 2, 8),
    (2, "HZ-B", "草案", 2, 9),
    (2, "JL-B", "签发", 2, 5),
    (7, "HZ-A", "签发", 10, 4),
    (7, "JL-A", "草案", 9, 0),
    (7, "JL-B", "签发", 10, 0),
    (7, "QH-A", "签发", 10, 7),
]
OLD = (8, 4, 4, 5, None, 7, 4, None, 5, 2, 6, 5)
# case, date, customer reply. Some confirmations arrive after the audit cut.
REPLIES = [
    (1, 4, "确认"),
    (2, 7, "确认"),
    (3, 4, "确认"),
    (4, 4, "退信"),
    (6, 4, "退信"),
    (7, 4, "确认"),
    (9, 6, "确认"),
    (10, 5, "确认"),
    (11, 4, "确认"),
]
CAP = [8, 7, 6, 6]
HISTORY = {
    "夜班异议": ("案号", "原批准", "原实发", "4日回条", "现批准", "处置"),
    "夜班结班": ("案号", "本班投递数", "最后回执", "12日状态"),
}
NOTICES = {
    1: " 同时接手夜班预约，请先读 input/办公室/夜班预约规程.txt，原件在夜班档案。",
    2: " 夜班签单为当班交接件，明日归还，请保存需要的事实。",
    4: " 夜班历史回条按收到日陆续入档，注意内审截点。",
    7: " 再接一批夜班签单，核对局部改动与生效日，明日原件归还。",
    8: " 换班班长还要接手夜班预约。按规程填写 out/夜班预约.xlsx，使输入改变后能在 Calc 自动重算。",
    9: " 今天的夜班调度单已到。用昨天的交班表办理调拨和撤单，更新数值和公式并交付。",
    11: " 另有十二笔上班遗留夜班异议。逐案填夜班异议页，依夜班规程只向需要处置的客户发信。",
    12: " 夜班终班先按今日指令更新夜班预约表，再按实际本班 H 案邮件交夜班结班页。",
}
RULES = """夜间保障业务与日间工位分账。案号 H01 至 H12，各案的对象、基准夜班额度、优先顺位和夜站见队列。额度依对象在业务日已经生效的最后一份正式签发，草案不生效；无变更沿用基准。签单随经手人仅开放当天。
预约工位：夜站容量依起始容量逐笔加减，调出站减、调入站加。每案需求为 max(0, 当日批准额度－关联首批 P 案截至6月4日的实际占位－截至今日部分验收数)，撤单后为0。关联 P 案只算6月3日实际投递的非退信原件，一封一笔，其冻结附件按日间占位规则核。夜班撤单只解除预约，不改变批准额度及旧件异议处置。
out/夜班预约.xlsx 模板单元格作为交班接口，保留顺序、键、页名和标题，允许增加辅助表。容量!B2:B5 是可直接修改的整数容量；队列!C2:C13 是可直接修改的整数需求。填写当日真实输入。队列!D2:D13 填实际安排、E2:E13 填未排；均须可重算。逐站按队列表自上而下分，允许部分满足：依次用剩余额度满足本案，余下需求进入未排。接班人可单独改站容量、单案需求或同时改动多个输入，其他行随之重算。8、9、12日各留档一次。夜班容量独立于日间现场附页。
内审：夜班异议页每案写原批准（6月3日）、原实发（上班夜件额度，缺件写未发）、4日回条（未发/待确认/确认/退信）、现批准（11日）和处置。判断顺序：现批准为0先暂缓；缺件则首发；最近回条退信则重投；原件额度不符当时授权则勘误；其余已确认写关闭，否则跟进。确认较晚也不能回填4日报表。原件正确而后续才改变额度本身不触发勘误。
只有首发、重投、勘误才在11日真正投递，分别发给该客户当日发布、备用、勘误邮箱（未另设勘误邮箱时取现行发布地址）。主题用夜班案号本身，每案一封，附件 UTF-8 文本独立行“对象：客户-系列”“处置：动作”“夜班额度：当日整数”；这些信不签日间工位。禁止提前、额外或重复通知。模拟邮箱可查本班 H 案，旧班资料另由档案库提供。
12日夜班结班逐案登记本班所有真实 H 案投递次数、最后一封实际回执号和12日状态（未发/退信/待确认/已确认）。无投递的最后回执填无。"""


def obj(k):
    _, i, s = FIRST[IDS.index(k)]
    return object_id(i, s)


def initialize(work):
    put(work / "input", "办公室/夜班预约规程.txt", RULES)
    d = work / "input/夜班档案"
    csvfile(
        d / "队列.csv",
        "案号,对象,关联首批,夜站,基准额度,优先顺位",
        [(k, obj(k), "P" + k[1:], SITE[k], BASE[k], i) for i, k in enumerate(QUEUE, 1)],
    )
    csvfile(d / "容量.csv", "夜站,容量", zip(POOLS, CAP))
    csvfile(
        d / "旧班夜件.csv",
        "案号,发送日,实发额度",
        [(k, 3, n) for k, n in zip(IDS, OLD) if n is not None],
    )
    wb = load_workbook(work / "out/交接.xlsx")
    for title, cols in HISTORY.items():
        wb.create_sheet(title).append(cols)
    wb.save(work / "out/交接.xlsx")
    wb.close()
    wb = Workbook()
    cap = wb.active
    cap.title = "容量"
    cap.append(["夜站", "容量"])
    for site in POOLS:
        cap.append([site])
    q = wb.create_sheet("队列")
    q.append(["案号", "夜站", "需求", "实际安排", "未排"])
    for k in QUEUE:
        q.append([k, SITE[k]])
    wb.save(work / "out/夜班预约.xlsx")
    wb.close()


def release(work, t):
    d = work / "inbox" / f"06-{t:02}" / "夜班"
    if t in (3, 8):
        (work / "inbox" / f"06-{t - 1:02}" / "夜班/当班签单.csv").unlink()
    if t in (2, 7):
        csvfile(
            d / "当班签单.csv",
            "对象,性质,生效日,额度",
            [
                (o, kind, start, n)
                for batch, o, kind, start, n in AMENDMENTS
                if batch == t
            ],
        )
    replies = [(IDS[i - 1], day, state) for i, day, state in REPLIES if t == day]
    if replies:
        csvfile(d / "客户回条.csv", "案号,收到日,回条", replies)
    if t == 9:
        put(d, "调度单.txt", "从东港调3席至北仓；撤销 H03 的预约。")
    if t == 12:
        put(
            d,
            "调度单.txt",
            "从西湾调2席至南站；H08 已部分验收2席，H07 撤单。此前撤单和调拨继续生效。",
        )
    return NOTICES.get(t, "")
