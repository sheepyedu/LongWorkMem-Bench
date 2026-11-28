"""Customer-facing v2 field-service amendments and capacity paperwork."""

import csv
from hashlib import sha256
from openpyxl import load_workbook

from .scenario import FIRST, object_id, put

POOLS = ("东港", "西湾", "南站", "北仓")
EXTRA_TABS = {
    "附页追溯": (
        "案号",
        "原应签主站",
        "原应签凭证",
        "应配席位",
        "原实发席位",
        "截至4日实占",
    ),
    "席位交割": ("主站", "累计占用", "可用席位"),
}
NOTICES = {
    1: " 本期还承办现场服务席位，先读 input/办公室/现场服务约定.txt。",
    2: " 评审稿须包含现场服务附页，使用本日拟稿批次。今日的签发名册只随签发邮件提供一天，请自行留档。",
    3: " 首批各案的现场附页依照本批申请与签署文件办理。",
    4: " 退信与固定旧件补办均须重新核定当日现场席位，不能原数照抄。",
    5: " 通讯页必须有 HZ、JL；其他四家可留空，也可保留其正确职责。",
    6: " 新网点须结合此前确实发出的席位和当天有效的站点授权安排。",
    7: " 转站单已到，注意生效与撤销日期；今日签发名册仅本日可阅。",
    9: " 本批使用当天的路由、凭证及真实结转余量。",
    10: " 附页随时限变化的两份新版重新签发；本批通知范围按时限变化判定。",
    11: " 六个审计案另填附页追溯页。实际勘误信沿用今天的现场附页制度。",
    12: " 席位交割页列四个主站截至今日的累计占用及可用席位。",
}
RULES = """现场换机工位六月签署办法
1. 每份草稿和投递的 Markdown 除原有行外，须各有唯一一行“服务主站：站名”“服务凭证：编号”“预留席位：整数”。三栏构成同一份客户服务附页，0代表有权受理但本批转候补。
2. 按对象查历史站点底册。分批签署文件须同时满足：正式件、签发人获本批对应对象授权、开始日≤业务日≤结束日、指定原单尚未在当日被撤销。在所有满足条件的单据中按(开始日,签发流水数值)取最大。到期或撤销后重选余下有效单，不影响早期发件。无有效签署单时回底册。签发名册按签署日查。六位客户的 A、B 系列分别管理。
3. 凭证按主站与该案服务类别从凭证册选择。修订仅对指定站和类别自生效日开始替换，其他列维持原值。申请档案中一案可有多张设备条：同一设备序号只认修订号最大的一行。该行若为取消则不占；其余的申请席位相加。案号以档案为准，不从其他批次推测。
4. 主站有固定容量及分期增额。每日本批先求日初余量：截至今天生效的各笔容量之和，减去前几日截至今天仍占用的实际投递。草稿不实际占位。每一封真实投递（含重发）按冻结附件的站及非负整数席位记入；退信从出现当日起释放；待确认和已确认均占。站名或席位行无效记0，其他行出错不影响这笔实际占用。实际错误造成负余量时，后续可签数按0。规则保留真实占用以便交割。
5. 本批按服务申请档案的优先号升序（同号按案号）依次分配，不按工具调用顺序。只纳入当日应办的案。若余量足够，签全部需求并扣减；不足则签0，余量留给下一案。补办和勘误是新的申请。R2仅对四份预定草稿演算，各批互相独立，R3按实际放行范围重算。当天如有多次同主题真实发件，次日起每封均会占用。
6. R11附页追溯每案填写R3当时应签的站、凭证和席位，R3实际投递的席位列表（分号隔开，未投递填未发，无效数字填无效），以及该案原件截至R4仍占用的席位。勘误触发条件包括首批附页不符；固定L03-C照办。R12结班表的累计占用含今日仍有效的所有历史投递，剩余报容量减实占的有符号数。
"""
CAPACITY = [
    (1, "东港", 8),
    (1, "西湾", 9),
    (1, "南站", 7),
    (1, "北仓", 8),
    (6, "东港", 3),
    (7, "南站", 3),
    (9, "北仓", 2),
    (10, "西湾", 4),
]
REVISIONS = [
    (6, "东港", "驻场", "DK-62"),
    (9, "西湾", "送修", "XW-91"),
    (10, "北仓", "驻场", "BC-74"),
]


def signer(obj, batch):
    return "员" + sha256(f"签批/{batch}/{obj}".encode()).hexdigest()[:5].upper()


def bases():
    return {
        object_id(i, s): POOLS[(j * 3 + j // 4) % 4]
        for j, (_, i, s) in enumerate(FIRST)
    }


def documents():
    rows = []
    for j, (_, i, s) in enumerate(FIRST):
        obj = object_id(i, s)
        for index, (batch, start, end, offset) in enumerate(
            [(2, 2, 12, 1), (2, 3, 5, 2), (2, 4, 8, 3), (7, 9, 12, 2), (7, 10, 11, 1)]
        ):
            serial = batch * 1000 + j * 5 + index
            valid_person = not (index == 2 and j % 2 == 0 or index == 4 and j % 3 == 0)
            official = not (index == 1 and j % 3 == 1)
            rows.append(
                (
                    serial,
                    obj,
                    batch,
                    start,
                    end,
                    POOLS[(j + offset) % 4],
                    signer(obj, batch) if valid_person else "员代签",
                    "正式" if official else "草案",
                )
            )
    return rows


def withdrawn():
    return [(7, 2000 + j * 5) for j in (0, 3, 5, 8)] + [
        (10, 7000 + j * 5 + 3) for j in (1, 4, 9)
    ]


def orders(t):
    scopes = {
        2: ["P01", "P02", "P04", "P09"],
        3: [k for k, _, _ in FIRST],
        4: [k + "-R" for k, _, _ in FIRST] + ["L01-R", "L02-R"],
        6: [f"N{n:02}" for n in range(1, 5)],
        9: ["T01", "T02", "T03"],
        10: ["U" + k[1:] for k, _, _ in FIRST],
        11: [k + "-C" for k in ("P01", "P02", "P04", "P05", "P09", "P10", "L03")],
    }
    rows = []
    for k in scopes.get(t, []):
        v = int.from_bytes(sha256(f"17217:{t}:{k}".encode()).digest()[:4], "big")
        cat = ("驻场", "送修")[v % 2]
        priority = v % 89 + 1
        for seq in range(3):
            ident = f"{k}-{seq + 1}"
            units = 1 + (v >> (seq * 2)) % 3
            rows.append((k, priority, cat, ident, 1, units, "有效"))
            if seq == 0:
                rows.append(
                    (
                        k,
                        priority,
                        cat,
                        ident,
                        2,
                        units + 1,
                        "有效" if v % 3 == 0 else "取消",
                    )
                )
        rows.append(rows[-1])  # duplicate synchronization
    return sorted(rows, key=lambda r: sha256(str((r, t)).encode()).digest())


def csvfile(path, head, rows):
    path.parent.mkdir(exist_ok=True, parents=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head.split(","))
        w.writerows(rows)


def initialize(work):
    put(work / "input", "办公室/现场服务约定.txt", RULES)
    d = work / "input/现场服务"
    csvfile(d / "站点底册.csv", "对象,主站", bases().items())
    csvfile(
        d / "凭证册.csv",
        "主站,服务类别,凭证",
        [
            (p, c, f"S{i + 1}{n + 1}")
            for i, p in enumerate(POOLS)
            for n, c in enumerate(("驻场", "送修"))
        ],
    )
    csvfile(d / "期初容量.csv", "生效日,主站,增额", [r for r in CAPACITY if r[0] == 1])
    wb = load_workbook(work / "out/交接.xlsx")
    for name, headers in EXTRA_TABS.items():
        wb.create_sheet(name).append(headers)
    wb.save(work / "out/交接.xlsx")
    wb.close()


def release(work, t):
    inbox = work / "inbox" / f"06-{t:02}"
    if t in (3, 8):
        (work / "inbox" / f"06-{t - 1:02}" / "值班签发名册.csv").unlink()
    if t in (2, 7):
        csvfile(
            inbox / "值班签发名册.csv",
            "对象,授权签发人",
            [(o, signer(o, t)) for o in bases()],
        )
        for serial, obj, b, start, end, site, who, kind in documents():
            if b == t:
                put(
                    inbox,
                    f"签署附件/{obj}/{serial}.txt",
                    f"对象 {obj}；签发流水 {serial}；签署日 {b}；类别 {kind}；签发人 {who}；有效期 第{start}日至第{end}日（含）；主站 {site}。",
                )
    for name, header, data in [
        ("撤单", "生效日,原流水", withdrawn()),
        ("凭证修订", "生效日,主站,服务类别,新凭证", REVISIONS),
        ("新增席位", "生效日,主站,增额", CAPACITY),
    ]:
        batch = [r for r in data if r[0] == t]
        if batch and t != 1:
            csvfile(inbox / (name + ".csv"), header, batch)
    rows = orders(t)
    if rows:
        csvfile(
            inbox / "设备申请.csv",
            "案号,优先号,服务类别,设备序号,修订号,申请席位,状态",
            rows,
        )
    return NOTICES.get(t, "")
