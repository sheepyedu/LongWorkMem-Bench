"""Public desk and staged mail for one continuous June service release."""

from openpyxl import Workbook


CUSTOMERS = ("海州", "江临", "南浦", "榆川", "清河", "北安")
CODES = ("HZ", "JL", "NP", "YC", "QH", "BA")
PRODUCTS = ("A", "B")
ROUNDS = range(1, 13)
# (case, customer index, product); two objects on hold at the first release.
FIRST = [(f"P{i + 1:02}", i // 2, PRODUCTS[i % 2]) for i in range(12)]
NEW = [("N01", 0, "A"), ("N02", 0, "B"), ("N03", 1, "B"), ("N04", 4, "A")]
LAST = [("T01", 0, "A"), ("T02", 1, "B"), ("T03", 4, "A")]
UPDATE = [("U" + k[1:], i, s) for k, i, s in FIRST]
AUDITS = ["P01", "P02", "P04", "P05", "P09", "P10"]
LEGACY = ["L01", "L02", "L03", "L04"]
TABS = {
    "期初": ("对象", "当前版"),
    "待办": ("案号", "状态", "下一步"),
    "变更": ("对象", "处置"),
    "回执": ("案号", "截点状态"),
    "通讯": ("客户", "新发布", "旧件确认", "勘误"),
    "排期": ("对象", "生效日", "行动"),
    "值班": ("席位", "负责人"),
    "追溯": ("案号", "当时应发", "实际附件", "确认数", "现行时限"),
    "交割": ("案号", "状态", "下一步", "责任邮箱"),
}
MANUAL = """六月服务手册发布规程 / 6月1日至12日，一天一个批次
部门共享盘 input/ 和 inbox/ 只读。out/、notes/、scratch/ 可写并跨委托保留。
在 out/交接.xlsx 按原页签和表头维护台账，每页一键一行，登记当轮委托所列对象。可留下先前行，无需创建额外汇报。对象键为客户代码-系列，例如 HZ-A。客户列填客户代码。
对每笔发件交一份 UTF-8 Markdown，包含单独一行“对象：HZ-A”和单独一行“换机时限：7个工作日”（示例）。其他措辞自由。时限必须包括单位。草稿与投递均用案号作邮件主题，每案一信一附件；同一案补办时使用当轮指定主题。模型拟写的附件可用任意 out/ 相对路径。表内只保留该页委托指定的案件，每页只需填写一次或按新来件更新。客户无单独变更时三种职责同为现行发布邮箱。收件人取该对象的职责邮箱。
正式条款按客户、系列和生效日期判断；签署的专项优先于通用办法，未签建议不生效。时间采用题中六月业务日，含当日。旧批次签收追认与今日发布、勘误的责任可不同。
receipt_query 查本场实际发件和截至业务日的状态，案号为空表示全部；用回执号查当时附件。草稿不算投递。状态用 未发、退信、待确认、已确认。退信可按授权重投，待确认仅跟进。晚到确认不能计入更早的截点。
追溯表的实际附件填写首批截点（第3日末）该主题下全部真实投递的时限，多个用分号（含真实重复），没有填未发。附件缺失或条款冲突填条款无效。确认数按截止日已确认的投递数。交割状态按实际最后一次投递判断，无投递填未发。"""
PROMPTS = [
    "接手六家客户。按5月31日登记的在用手册版本填期初页（12个对象），并把上班四笔遗留案截至今日的状态、下一步填待办页。先理清，暂缓发件。",
    "按今日签署材料准备六月版，变更页登记来件列出的三项提案处置（采用、待签）。按评审单实际拟稿，暂缓投递。",
    "首批放行通知到了。按名单和有效规则实际投递，暂缓案不要发送。",
    "截至今天先核对首批通知上12案的状态，填回执页。按异常办理单处理本批退信与旧班错件。",
    "渠道部变更了两家客户的职责邮箱。仅更新通讯页，分别记下新发布、旧件确认和勘误邮箱。",
    "为四个新增网点发送目前有效的手册，按开户单案号及对应客户的日常发布邮箱办理。",
    "登记今天的验收和待签建议。排期页填来件的三个对象、生效日（六月日号或待定）及行动（切换或待签）。请勿提前发送。",
    "临时处理周五两席换班。按设施部最后签署的调班单更新值班页，其余发布工作稍后继续。",
    "回到发布。今天是切换前最后一天，请按当天口径办完三笔新申请。",
    "办理今日差量发布。候选清单列出所有对象，只给今日条款实际改变的对象发送新版，其余无需打扰。",
    "内审提出异议，按异议单还原当时批准、首批实际附件、截至第4日的确认数和现行时限，填追溯页；需要补救的今天实际办理。",
    "请按结班清单逐案交割，交割页给出今天的真实状态、下一步和负责邮箱。已办结要有真实确认；请勿另发邮件。",
]


def put(folder, name, text):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def object_id(i, s):
    return f"{CODES[i]}-{s}"


def address(i, role="service"):
    return f"{CODES[i].lower()}.{role}@office.test"


def listing(rows):
    return "案号,对象\n" + "".join(f"{k},{object_id(i, s)}\n" for k, i, s in rows)


def opening_version(i, s):
    return f"05-{i + 1:02}-{1 if s == 'A' else 2}"


def init(work):
    inp = work / "input"
    put(inp, "办公室/发布规程.txt", MANUAL)
    wb = Workbook()
    wb.remove(wb.active)
    for name, headers in TABS.items():
        wb.create_sheet(name).append(headers)
    wb.save(work / "out/交接.xlsx")
    put(
        inp,
        "客户档案/索引.csv",
        "代码,客户,现行发布邮箱\n"
        + "".join(
            f"{code},{name},{address(i)}\n"
            for i, (code, name) in enumerate(zip(CODES, CUSTOMERS))
        ),
    )
    for k, i, s in FIRST:
        obj = object_id(i, s)
        put(
            inp,
            f"客户档案/{CUSTOMERS[i]}/在用/{obj}.md",
            f"# 在用登记\n对象：{obj}\n版号：{opening_version(i, s)}\n登记日：05-31\n",
        )
    # Separate business records with stable IDs, site, product, dates and owner.
    for j in range(192):
        i = j % 6
        s = PRODUCTS[(j // 6) % 2]
        month = 1 + (j // 12) % 4
        branch = j // 48 + 1
        put(
            inp,
            f"客户档案/{CUSTOMERS[i]}/历史/{month:02}/{s}-{j:03}.md",
            f"# 服务通告 H{j:03}\n对象：{object_id(i, s)}\n站点：第{branch}分站\n版号：{month:02}-{branch}\n"
            f"换机时限：{3 + (j * 7) % 16}个工作日\n适用：当月历史批次\n保管人：{address(i)}\n",
        )
    for j in range(256):
        i = j % 6
        line = ("配件", "维修", "安装", "租赁")[j % 4]
        put(
            inp,
            f"渠道伙伴/{CUSTOMERS[i]}/{line}/工单-{j:03}.csv",
            f"伙伴工单,客户,业务线,受理网点,应答日数,状态\nQ{j:04},{CODES[i]},{line},区站{j % 19:02},{2 + j % 8},{('已交接', '待报价', '备件在途')[j % 3]}\n",
        )
    for j in range(96):
        team = ("设施", "培训", "人事", "会务")[j % 4]
        put(
            inp,
            f"部门共享/{team}/{j:03}.txt",
            f"五月{team}事项 {j:03}，归口{j % 9 + 1}组。值班席{j % 5 + 1}，计划日{j % 28 + 1}，原排班{('孙芸', '陈江', '任凯')[j % 3]}。本件已归档。\n",
        )
    for j in range(69):
        i = j % 6
        s = PRODUCTS[(j // 6) % 2]
        put(
            inp,
            f"客户档案/{CUSTOMERS[i]}/服务网点/{j:03}.csv",
            f"网点号,客户,产品,网点名称,归口\nWD{j:03},{CODES[i]},{s},{CUSTOMERS[i]}服务{j // 6 + 1}站,{address(i)}\n",
        )
    put(
        inp,
        "办公室/上班遗留.csv",
        "案号,对象,状态,下一步,来源\n"
        "L01,HZ-A,已确认,勘误,客户已确认旧件但条款有误\nL02,JL-B,退信,重投,地址已失效\n"
        "L03,NP-A,待确认,跟进,已送达待回复\nL04,YC-B,已确认,关闭,已验收\n",
    )


def release(work, t):
    inbox = work / "inbox" / f"06-{t:02}"
    if t == 2:
        put(
            inbox,
            "服务部签发.txt",
            "六月通用换机时限10个工作日。HZ-A在服务点书面验收生效前维持7个工作日；JL-B在试点获准退出前维持5个工作日。变更页登记 HZ-A、JL-B、QH-A 三项专项提案。",
        )
        put(inbox, "渠道建议.txt", "未签建议：QH-A改成3个自然日。等待服务部签批。")
        put(
            inbox,
            "评审单.csv",
            listing([FIRST[i] for i in (0, 1, 3, 8)])
            + "评审均拟给各客户原发布邮箱，主题仍为对应P案号。",
        )
    elif t == 3:
        put(
            inbox, "第一批放行.csv", listing(FIRST) + "\n暂缓：P08、P12。其余10案放行。"
        )
    elif t == 4:
        put(
            inbox,
            "异常办理.txt",
            "已实际退信的首批案用原主题加-R重新投递，到该客户 code.backup@office.test（code小写）。L01旧件发错与L02退信固定补办，用L01-R、L02-R主题发至各自备用邮箱，内容用今日有效口径。待确认只登记。",
        )
    elif t == 5:
        put(
            inbox,
            "渠道签发.txt",
            "今日起 HZ、JL 的日常发布改为 code.new@office.test，旧件确认沿用 code.service@office.test，勘误由 code.review@office.test 接收。code使用客户小写代码。其他客户三种职责均由原发布邮箱负责。",
        )
    elif t == 6:
        put(inbox, "开户单.csv", listing(NEW))
    elif t == 7:
        put(
            inbox,
            "验收签发.txt",
            "HZ-A 新服务点验收通过，第10日起采用通用条款；JL-B试点同日退出，但签署的新条款为8个工作日。QH-A建议仍待签，生效日待定。",
        )
    elif t == 8:
        put(
            inbox,
            "设施部签发.txt",
            "周五席位东台改由赵宁、西台改由吴禾值班；五月旧排班已归档。仅更新交接表。",
        )
    elif t == 9:
        put(inbox, "末班申请.csv", listing(LAST))
    elif t == 10:
        put(inbox, "迁移候选.csv", listing(UPDATE))
    elif t == 11:
        put(
            inbox,
            "内审异议.txt",
            "核对 "
            + "、".join(AUDITS)
            + "。对象按首批名单，实际附件列同主题全部投递，不含补办主题。"
            "若首批原案的实际投递数不是1，或该唯一邮件的收件人、附件对象、时限有一项不符，今天以原案号加-C给现勘误邮箱补送现行手册。已正确履约而仅等待回复的不用补送。"
            "另外固定纠正上班遗留L03登记的附页遗漏，按NP-A现行口径发L03-C至现勘误邮箱。",
        )
    elif t == 12:
        put(
            inbox,
            "结班清单.txt",
            "逐案核对 P01、P03、P03-R、L01-R、L02-R、N01、N03、T01、U01、U04、L03-C。"
            "原案和补办各自留档；已确认=关闭，退信=重投，待确认=跟进，未发=核实。"
            "跟进/关闭填旧件确认邮箱，重投/核实填当前发布邮箱。状态按该主题最后一次投递取。",
        )
    return f"6月{t}日。" + PROMPTS[t - 1]
