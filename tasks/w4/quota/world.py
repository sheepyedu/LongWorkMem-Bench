"""Fixed, publicly staged documents for the four-station service desk."""

from openpyxl import Workbook

from ..annex import POOLS, csvfile
from ..scenario import init, put

# case, object, station, opening reservation, protected, charter ceiling, priority
CASES = [
    ("J01", "HZ-A", "东港", 4, 3, 4, 2),
    ("J02", "JL-B", "东港", 1, 0, 5, 1),
    ("J03", "NP-B", "东港", 3, 1, 3, 3),
    ("J04", "HZ-B", "西湾", 1, 0, 5, 2),
    ("J05", "YC-A", "西湾", 4, 3, 4, 3),
    ("J06", "QH-B", "西湾", 2, 1, 4, 1),
    ("J07", "JL-A", "南站", 3, 2, 4, 3),
    ("J08", "BA-B", "南站", 2, 1, 5, 2),
    ("J09", "QH-A", "南站", 3, 0, 4, 1),
    ("J10", "NP-A", "北仓", 1, 1, 4, 1),
    ("J11", "YC-B", "北仓", 4, 2, 4, 2),
    ("J12", "BA-A", "北仓", 2, 0, 5, 3),
]
IDS = [r[0] for r in CASES]
INFO = {r[0]: r[1:] for r in CASES}
CAP = dict(zip(POOLS, (8, 7, 8, 7)))


# Document issue date, effective date inclusive, expiry inclusive, case, signer, kind, ceiling, priority.
def documents():
    rows = []
    for i, (k, obj, site, _, _, _, _) in enumerate(CASES):
        for series, (batch, start, end, signer, kind, ceil, rank) in enumerate(
            [
                (
                    2,
                    3,
                    12,
                    "本部",
                    "正本",
                    [5, 3, 4, 4, 5, 3, 5, 4, 5, 3, 5, 3][i],
                    [3, 1, 2, 1, 2, 3, 2, 3, 1, 2, 3, 1][i],
                ),
                (
                    2,
                    3,
                    8,
                    "本部",
                    "正本" if i % 3 != 0 else "草案",
                    2 + (i + 1) % 5,
                    1 + i % 3,
                ),
                (7, 9, 12, "代办", "正本", 2 + i % 5, 1 + (i + 2) % 3),
                (
                    7,
                    10,
                    12,
                    "本部",
                    "正本" if i % 3 != 2 else "待批",
                    2 + (i + 3) % 5,
                    1 + i % 3,
                ),
            ]
        ):
            rows.append(
                (
                    1000 * batch + 10 * i + series,
                    batch,
                    start,
                    end,
                    k,
                    signer,
                    kind,
                    ceil,
                    rank,
                )
            )
    return rows


SCOPES = {"东港": "A", "西湾": "B", "南站": "B", "北仓": "A"}
WITHDRAW = {9: (2010, 2070), 10: (7002, 7103, 7033)}
# A station's operating pool moves as a pair. These are physical, not paper capacities.
CAP_CHANGES = {
    9: {"东港": -1, "西湾": 1, "南站": 1, "北仓": -1},
    10: {"东港": 2, "西湾": -2},
}
# Only the specified clients consent to unblocking their protected reservations.
UNLOCK = {9: ("J01", "J08"), 10: ("J05", "J11")}
# External partial collection frees physical seats and advances the case version.
PICKUPS = {
    4: {"J01": 1, "J07": 1},
    9: {"J04": 1, "J10": 1},
    11: {"J02": 1, "J06": 2, "J09": 1, "J12": 1},
}
PENDING = {
    3: ("J01", "J05", "J08", "J12"),
    9: ("J03", "J04", "J07", "J11"),
    10: ("J02", "J06", "J08", "J12"),
    11: ("J02", "J06", "J09", "J12"),
}
CO_SIGN = {
    3: ("J02", "J04", "J07", "J10"),
    9: ("J02", "J05", "J08", "J12"),
    10: ("J01", "J04", "J09", "J11"),
    11: ("J02", "J06", "J09", "J12"),
}
# Signed reciprocal claims; release of a voucher depends on a different case's real day-3 close.
VOUCHERS = {
    k: (
        IDS[i ^ 1],
        (5, 6, 4, 5, 6, 4, 5, 6, 5, 4, 6, 5)[i],
        1 + i % 3,
        9 + (i % 4 == 2),
        10 + (i % 3 != 1),
    )
    for i, k in enumerate(IDS)
}
VOID = {10: ("J01", "J08"), 11: ("J05", "J10")}
CHALLENGES = ("J01", "J05", "J08", "J11")
ROUTES = {"HZ": "复核", "NP": "复核", "BA": "复核"}
FILES = {
    1: ("接班", ("原席", "锁定", "章程额度")),
    2: ("授权", ("批文", "额度", "优先号")),
    4: ("回查", ("三日实占", "今日实占", "当前版本")),
    5: ("通讯", ("解释邮箱", "维持邮箱")),
    6: ("委托", ("本站代办系列", "本站代办末日")),
    7: ("排期", ("九日批文", "十日候选批文", "来源三日实占", "九日预兑")),
    11: ("异议", ("三日实占", "十日实占", "开班实占", "今日目标", "通知")),
    12: ("结班", ("实占", "版本", "最后受理号")),
}
DISPATCH = ("批文", "基础额度", "兑入", "额度", "优先号", "目标", "实占", "最后受理号")
PROMPTS = [
    "接手四站六月预约，读发布规程和有效档，交接班表。归档里还保留上一期的旧手册。",
    "审核今日流转件，按第3日应生效的口径交授权表。签单只借本班。",
    "执行首批调度，递交调度表，次日有人来取件。",
    "按实际回执追查昨天结班与今天开班的差别，交回查表。今天不改席位。",
    "渠道通知到了。登记各案解释以及维持原承诺的联络邮箱。",
    "临时接手委托移交。登记各案所在站的代办范围和失效日。原授权仍须保留。",
    "新一批签单到件；仅依据截至今日已知材料，预排9日、10日两次授权，交排期表。本班不调度。",
    "班长接岗，用第9日已知的计划排一份可重算的预约表。交班后还可能收到撤单。",
    "回到站务；办理本日回单、撤销和调拨，实际调度并交表。",
    "按最新生效范围差量调度，禁止为无变化客户另发指令。交当日调度表。",
    "客户提出异议。按截点还原历史，先完成今日必要调度，再按规程向指定对象真实通知，交异议表与当日调度表。",
    "终班，仅交结班表和可改参数的预约表。账上要能区分真实受理号与模拟推算。",
]
RULES = """六月四站服务承诺与排班规程。input/档案为旧材料；本期以 input/站务 和分日 inbox 为准。日期为六月日号，区间含首尾，四站互不借位（调拨通知除外）。每日简报只需列异常，无需重抄表格。
授权：章程是兜底（批文号填“章程”）。在当天已收到、已生效、未到期且截至当天未撤的正本中，按(生效日,流水数值)最大取一整份额度及优先号。签发人本部有效；代办还必须符合委托的站、系列和办理日，过期即回选，不追改早期。排期只用第7日下班已知材料，不能推断未来来件。
跨站续办券以第2日限时借阅的签单为准。签单列兑现对象、来源案、保证基数、转入上限和有效期。来源只认第3日结班真实实占（不采用其目标或次日提取后的数）。在有效期且未收到当日生效的注销单时，兑入=min(转入上限,max(0,保证基数−来源三日实占))；否则为0。调度额度=基础额度+兑入。正数兑入案优先号在原批文基础上减1（允许0），其余用原优先号。调度.csv 中优先号填最终值。第7日排期仍按当时已知材料。
调度：先保留每案当前锁定席，再用本站总容量减全站锁定量；按有效优先号升序、同号按案号，把剩余量依次补给各案，最多至批准额度（额度低于锁定时保留锁定数）。实际占位会因提取、真实申请或撤销确认改变。应减的先减，应增的再增。收到客户同意解除锁定只降低保留底线，实际席位仍须由柜面调整。由于转站调拨可能临时超用，遇此情况先释放再加配。第8日预约预测沿用8日可查的锁定和容量，采用第9日已知授权；第12日用当日状态及授权。
用 receipt_query 查柜面：case 空或案号，as_of 为空或截至日，receipt 为空时返回案号、实占、锁定、版本、最后受理号和本站容量。要查当日变动前的状态，case 填“开班”或“开班/J01”。receipt 填真实的投递回执号可读整批逐行回单。无成功申请时最后受理号填“期初”。业务日只有3、9、10、11日开放申请，柜面按实际收到顺序逐行处理。
用 deliver 将 UTF-8 CSV 附件寄到 quota@office.test，主题固定“站务申请”。列名：案号,请求号,预期版本,目标席。版本为当前整数；请求号在整场内唯一（字母数字、短横或下划线）。同号同指令重试返回原回单，不再改账；同号异指令或版本落后退回。席位不足或受锁定保护时仅执行可办部分；受理会推进版本并给受理号，重复查询不推进。退回后需要新请求号、读取真实版本及余量再办。目标席填绝对数，同一案已达到目标无需发指令。只提交必要动作，禁止额外对客通知。整数型字段可不补零。所有额度及席位均为非负整数，请求号长度1至64。每批最多12行，可同轮分多批。柜面不替运营审核签署权限或优先级。当天会签清单内的案件，第一笔有效变更若跨两席及以上，柜面只先办一席，返回的版本已更新。余量、锁定和本轮其他案件可能影响续办；同号重试不会办第二次。另有异步承运回传名单：每案当日第一笔版本正确、确有变动的请求先触发承运回传，至多提走一席未锁定的预约并更新版本；柜面退回原请求。应核对新实占与版本，只在仍有差额时续办。这一事件由业务动作触发，与耗时无关。
第11日给主动询证名单，以及开班实占与当日应配不同的案件发通知，各案一封（两组重叠只发一次）；其余不发。主题为案号，附件单行CSV：案号,十日实占,今日目标,办后实占。需要调整的走解释邮箱；仅询证且开班即达目标的走维持邮箱。收件制度按第5日通知，未变更地址仍有效。
表格交 out/名称.csv，一案一行，UTF-8带表头，允许重排列和行。调度表统一叫调度.csv，每个调度日冻结今日数据。其他页见模板目录。空值不要猜回执。11日异议表通知栏填“解释”“维持”或“无”。不得在未开放日发信或改席位。
交班表 out/预约.xlsx 使用所附固定接口。容量页 A/B 为四个站及可再分容量（总容量减锁定合计），队列页 A/B/C/D/E 为案号、站、净需求、加配、候补，按当期有效优先顺序排列（全表按优先号、案号升序）。净需求=max(0,额度−锁定)。B2:B5容量及C2:C13需求是可直接改的整数；D/E 在 Calc 中自动按站从上往下分，允许部分满足；改变容量、单案需求后未影响客户也要正确。两日分别交付。"""


def initialize(work):
    init(work)  # reuse the customer archive and read-only/writable split
    put(work / "input", "办公室/发布规程.txt", RULES)
    d = work / "input/站务"
    csvfile(d / "章程.csv", "案号,对象,站,期初实占,期初锁定,章程额度,章程优先号", CASES)
    csvfile(d / "期初容量.csv", "站,容量", CAP.items())
    for name, cols in [*FILES.values(), ("调度", DISPATCH)]:
        csvfile(d / "表头" / (name + ".csv"), ",".join(("案号", *cols)), [])
    wb = Workbook()
    w = wb.active
    w.title = "容量"
    w.append(["站", "可再分容量"])
    for p in POOLS:
        w.append([p])
    wb.create_sheet("队列").append(["案号", "站", "净需求", "加配", "候补"])
    wb.save(work / "out/预约.xlsx")
    wb.close()


def release(work, t):
    d = work / "inbox" / f"06-{t:02}"
    if t in (3, 8):
        (work / "inbox" / f"06-{t - 1:02}" / "签发原件.csv").unlink()
    if t == 2:
        csvfile(
            d / "续办券.csv",
            "兑现案,来源案,保证基数,转入上限,生效日,末日",
            [(k, *v) for k, v in VOUCHERS.items()],
        )
    if t == 3:
        (work / "inbox/06-02/续办券.csv").unlink()
    if t in VOID:
        csvfile(d / "注销券.csv", "兑现案", [(k,) for k in VOID[t]])
    if t in (2, 7):
        csvfile(
            d / "签发原件.csv",
            "流水,签发日,生效日,到期日,案号,签发人,性质,额度,优先号",
            [r for r in documents() if r[1] == t],
        )
    if t == 5:
        put(
            d,
            "通讯签收.txt",
            "HZ、NP、BA 的解释函发 code.review@office.test，其余解释函和所有维持函发 code.service@office.test，code取对象客户代码小写。",
        )
    if t == 6:
        csvfile(
            d / "委托.csv",
            "站,代办系列,开始,末日",
            [(s, a, 9, 9 if s in ("东港", "北仓") else 11) for s, a in SCOPES.items()],
        )
    if t in PENDING:
        csvfile(d / "待承运回传.csv", "案号", [(k,) for k in PENDING[t]])
    if t in CO_SIGN:
        csvfile(d / "分次受理.csv", "案号", [(k,) for k in CO_SIGN[t]])
    if t in WITHDRAW:
        csvfile(d / "撤文.csv", "当日生效撤销流水", [(x,) for x in WITHDRAW[t]])
    if t in PICKUPS:
        csvfile(d / "提取回单.csv", "案号,提取上限", PICKUPS[t].items())
    if t in CAP_CHANGES:
        csvfile(d / "调拨.csv", "站,容量变动", CAP_CHANGES[t].items())
    if t in UNLOCK:
        csvfile(d / "解除保护.csv", "案号,新锁定", [(k, 0) for k in UNLOCK[t]])
    if t == 11:
        csvfile(d / "主动询证.csv", "案号", [(k,) for k in CHALLENGES])
    return f"6月{t}日。" + PROMPTS[t - 1]
