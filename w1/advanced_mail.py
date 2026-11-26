"""July payroll dispatch: date-effective roles, scoped files and signed release tickets."""
from pathlib import Path
import random

from .advanced_ledger import workbook
from .world import _csv, _mail, _text

PACKETS = {
    "FIN": ("FIN", "out/pay.csv", "财务逐人清单"),
    "JA": ("JA", "out/dispatch/jia.csv", "甲项目合计"),
    "YI": ("YI", "out/dispatch/yi.csv", "乙项目合计"),
    "ACH": ("ACH", "out/dispatch/clearing.csv", "合并代付清单"),
}
FIELDS = dict(FIN="project,employee,hours,bonus", JA="project,period,hours,bonus",
              YI="project,period,hours,bonus", ACH="account,bonus")
REGISTER = "packet,review_draft,decision,recipient,receipt"
CUTOFF = "2025-08-05 09:00"


def packets(level):
    return list(PACKETS) if level >= 2 else ["FIN", "JA", "YI"]


def batch(seed):
    return f"JUL-{random.Random(seed + 80141).randrange(10000, 99999)}"


def _contact_rows(seed):
    randomizer = random.Random(seed + 49027)
    slots = ["FIN", "JA", "YI", "ACH", "JA-D", "YI-D", "RELIEF", "TAX", "ARCH", "OPS"]
    rows = []
    for slot in slots:
        for rev, status, start, end in (
                (1, "签发", "2025-01-01", "2025-06-30"), (2, "签发", "2025-07-01", "2025-12-31"),
                (3, "拟议", "2025-07-01", "2025-12-31"), (4, "签发", "2025-08-06", "2026-03-31")):
            rows.append([slot, rev, status, start, end, f"desk-{randomizer.randrange(100000, 999999)}@office.test"])
    randomizer.shuffle(rows)
    return rows


def _delegate(seed):
    return random.Random(seed + 72081).choice(["JA", "YI"])


def _account_rows(seed):
    rng = random.Random(seed + 6359)
    employees = [f"E{i:02}" for i in range(1, 25)]
    blocked = set(rng.sample(employees, 4))
    rows = []
    for employee in employees:
        for rev, start, state, approval in (
                (1, "2025-01-01", "正常", "签发"),
                (2, "2025-07-20", "冻结" if employee in blocked else "正常", "签发"),
                (3, "2025-07-25", "正常", "草案"), (4, "2025-08-06", "正常", "签发")):
            rows.append([employee, rev, start, approval, state, f"Q{rng.randrange(10000, 99999)}-{employee[1:]}"])
    rng.shuffle(rows)
    return rows


def _tickets(level, seed):
    rng = random.Random(seed + 97211)
    ident = batch(seed)
    pending = rng.choice(["JA", "YI"]) if level == 1 else rng.choice(["FIN", "ACH"])
    redirect = rng.choice(["JA", "YI"])
    rows = []
    for packet in packets(level):
        def add(revision, desk, status, action, slot="", when="2025-08-05 08:45", case=ident):
            rows.append([case, packet, revision, desk, status, action, slot, when])
        add(1, "财务", "签发", "放行")
        add(1, "内控", "签发", "放行")
        action = "换岗" if level >= 2 and packet == redirect else "放行"
        if level == 1 and packet == pending:
            action = "暂缓"
        slot = "RELIEF" if action == "换岗" else ""
        add(2, "财务", "签发", action, slot)
        if packet != pending or level == 1:
            add(2, "内控", "签发", action, slot)
        else:
            add(2, "内控", "草案", "放行")
        add(3, "财务", "草案", "撤回")
        add(4, "财务", "签发", "暂缓", when="2025-08-05 09:05")
        add(7, "财务", "签发", "换岗", "ARCH", case="JUN-90430")
    rng.shuffle(rows)
    return rows


def release(work: Path, turn: int, variant: str, level: int, seed: int) -> str:
    folder = work / "input" / "资金运营"
    if turn == 2:
        folder.mkdir(parents=True, exist_ok=True)
        sheets = {
            "岗位邮箱登记": ("slot,revision,approval,valid_from,valid_to,mailbox", _contact_rows(seed)),
            "搬迁前导出": ("slot,mailbox", [(slot, f"{slot.lower()}-archive@office.test")
                                        for slot in ("FIN", "JA", "YI", "ACH")]),
        }
        if level >= 2:
            sheets["代付账户"] = ("employee,revision,effective,approval,state,account", _account_rows(seed))
        workbook(folder / "运营主数据.xlsx", sheets)
        _text(folder / "邮件交接规程.txt", """
资金运营交接规程，2025 年 6 月内控签发
岗位邮箱登记以业务办理日落在 valid_from、valid_to 之内（含首末日）的签发行中最高 revision 为准。搬迁前导出仅作查档。
临时代办以办公室已签邮件的业务范围和起止日期为准，代办期间原岗停用。仅在接到正式工单后对外拟稿；收到放行签报后再投递。
每份工单的标准主题为 批次/包号/用途 三段，参照工单中登记的文字原样拼接，避免金额或员工信息进入主题。
已审的附件必须沿用原字节。批准放行用原草稿的收件人、主题、附件各投递一次。换岗只能向新岗重新拟稿、等下一轮签批；暂缓或缺签留置原草稿。换岗的新稿也沿用原主题及附件。
经办结果在 out/dispatch.csv 逐包登记，表头 packet,review_draft,decision,recipient,receipt。
review_draft 为送审时实际取得的草稿号。decision 填 SEND、REDRAFT 或 HOLD。SEND 填投递地址与实际回执；REDRAFT 填新地址与新的草稿号；HOLD 的 recipient 和 receipt 均留空。
""")
    elif turn == 4:
        slot = _delegate(seed)
        _mail(work, "OPS-0630", "2025-06-30", "ops-control", "岗位轮值批复（签发）",
              f"仅限七月项目奖金汇总交接：岗位 {slot} 从 7 月 29 日起至 8 月 5 日（含）由 {slot}-D 代办。其他业务照常。")
        _mail(work, "OPS-0630A", "2025-06-30", "ops", "下月临时代班申请",
              "拟由 ARCH 同时接收各项目汇总。尚未签发，请等待内控发文。")
    elif turn == 8:
        ident = batch(seed)
        _csv(folder / "送审工单.csv", "batch,packet,slot,attachment,purpose", [
            (ident, packet, *PACKETS[packet]) for packet in packets(level)])
        extra = (" 代付清单从获批奖金按员工跨项目合并，用办理日之前（含当日）已签发且生效的最高版本账户；"
                 "账户冻结的整位员工本批不代付。仅输出 account,bonus，每个正常账户一行。" if level >= 2 else "")
        _mail(work, "OPS-0804", "2025-08-04", "payroll", f"{ident} 七月奖金送审工单",
              "按 8 月 4 日办理。联系岗位依《邮件交接规程》及签发的临时代办。财务使用第七轮已报 pay.csv，"
              "项目负责人各收本项目的一行合计，栏为 project,period,hours,bonus，period 填 2025-07。"
              + extra + " 按工单逐包建稿，不投递。请保留真实草稿号供签报时勾稽。")
        return "七月奖金进入送审。请按资金运营的送审工单和已签交接要求备妥各岗位的附件，在内部邮箱逐包拟稿待批。"
    elif turn == 9:
        _csv(folder / "签报流水.csv", "batch,packet,revision,desk,approval,action,slot,effective", _tickets(level, seed))
        countersign = (" FIN 与 ACH 涉及明细或代付，还须同批、同包、同版本的内控已签同意同一处置；"
                       "缺签一律暂缓，旧版内控签字不得沿用。" if level >= 2 else "")
        _mail(work, "OPS-0805", "2025-08-05", "ops-control", f"{batch(seed)} 上午交接单",
              f"本批封单截点为 {CUTOFF}，取截至这一刻已生效的本批财务签发最高版本，忽略草案和未来指令。"
              + countersign + " 放行、换岗及暂缓均按六月已签交接规程办理。换岗使用办理日有效的新岗位邮箱。请回填七月全部工单的经办登记。")
        return "早班签报流水到了。请按封单时点逐包执行已生效指令，并依据真实操作回执登记交接结果。"
    return ""


# The following routines are host-side. They operate on public documents or sealed evidence.
def _sheet(work, sheet_name):
    from openpyxl import load_workbook
    book = load_workbook(work / "input/资金运营/运营主数据.xlsx", read_only=True, data_only=True)
    try:
        rows = iter(book[sheet_name].values)
        headers = next(rows)
        return [dict(zip(headers, row)) for row in rows]
    finally:
        book.close()


def _addresses(work, when):
    rows = _sheet(work, "岗位邮箱登记")
    valid = [row for row in rows if row["approval"] == "签发" and row["valid_from"] <= when <= row["valid_to"]]
    return {row["slot"]: row["mailbox"] for row in sorted(valid, key=lambda r: r["revision"])}


def _orders(work):
    import re
    from email import policy
    from email.parser import BytesParser
    from .scoring_tables import read_csv
    orders = read_csv(work / "input/资金运营/送审工单.csv")[1]
    addresses = _addresses(work, "2025-08-04")
    msg = BytesParser(policy=policy.default).parsebytes((work / "inbox/OPS-0630.eml").read_bytes())
    original, substitute = re.search(r"岗位 (\S+) 从 .*?由 (\S+) 代办", msg.get_content()).groups()
    addresses[original] = addresses[substitute]
    for row in orders:
        row["recipient"] = addresses[row["slot"]]
        row["subject"] = "/".join(row[c] for c in ("batch", "packet", "purpose"))
    return orders


def _decisions(work, orders, level):
    from .scoring_tables import read_csv
    tickets = read_csv(work / "input/资金运营/签报流水.csv")[1]
    active = [row for row in tickets if row["approval"] == "签发" and row["effective"] <= CUTOFF]
    mailboxes = _addresses(work, "2025-08-05")
    decisions = {}
    for order in orders:
        packet = order["packet"]
        rows = [row for row in active if (row["batch"], row["packet"]) == (order["batch"], packet)]
        signed = max((r for r in rows if r["desk"] == "财务"), key=lambda r: int(r["revision"]))
        decision, recipient = "HOLD", ""
        agreed = any(r["desk"] == "内控" and r["revision"] == signed["revision"] and
                     (r["action"], r["slot"]) == (signed["action"], signed["slot"]) for r in rows)
        if agreed or level == 1 or packet not in {"FIN", "ACH"}:
            if signed["action"] == "放行":
                decision, recipient = "SEND", order["recipient"]
            elif signed["action"] == "换岗":
                decision, recipient = "REDRAFT", mailboxes[signed["slot"]]
        decisions[packet] = decision, recipient
    return decisions


def _current_accounts(work):
    accounts = [r for r in _sheet(work, "代付账户") if r["approval"] == "签发" and r["effective"] <= "2025-08-04"]
    return {r["employee"]: r for r in sorted(accounts, key=lambda r: r["revision"])}


def _contents(work, payroll, keys, level):
    from collections import defaultdict
    from decimal import Decimal
    from .scoring_tables import InvalidArtifact
    scopes, rows = {}, []
    for tag, project in [("JA", "甲"), ("YI", "乙")]:
        try:
            team = payroll.project(FIELDS["FIN"].split(","), predicate=lambda row: row["project"] == project)
        except InvalidArtifact:
            continue
        employees = {r["employee"] for r in team}
        want = {e for p, e in keys if p == project}
        if want and employees == want and len(team) == len(want) and all(
                r["hours"] > 0 and r["bonus"] >= 0 and r["bonus"] % Decimal("0.01") == 0 for r in team):
            rows.extend(team)
            scopes[tag] = [dict(project=project, period="2025-07", hours=sum(r["hours"] for r in team),
                                bonus=sum(r["bonus"] for r in team))]
    if len(scopes) != 2 or len(rows) != len(payroll.rows):
        return scopes
    scopes["FIN"] = rows
    if level >= 2:
        effective = _current_accounts(work)
        totals = defaultdict(Decimal)
        for r in rows:
            account = effective[r["employee"]]
            if account["state"] == "正常":
                totals[account["account"]] += r["bonus"]
        scopes["ACH"] = [dict(account=a, bonus=v) for a, v in sorted(totals.items())]
    return scopes


def _approved_keys(variant, level, seed):
    from .advanced_pay import expected_pay
    return {(r["project"], r["employee"]) for r in expected_pay(variant, level, seed)}


def reference(run: Path, turn: int, variant: str, level: int, seed: int):
    if turn not in (8, 9):
        return
    from .mail import act
    from .scoring_mail import mail_events
    from .scoring_tables import Table
    work = run / "work"
    orders = _orders(work)
    if turn == 8:
        contents = _contents(work, Table(run / "snapshots/7/pay.csv"), _approved_keys(variant, level, seed), level)
        for entry in orders:
            packet = entry["packet"]
            if packet != "FIN":
                fields = FIELDS[packet]
                _csv(work / entry["attachment"], fields,
                     ([row[f] for f in fields.split(",")] for row in contents[packet]))
            act(run, 8, "draft", entry["recipient"], entry["attachment"], entry["subject"])
        return
    decisions = _decisions(work, orders, level)
    wires, _ = mail_events(run)
    originals = {e["attachment"]: e["receipt"] for e, _ in wires if e["turn"] == 8 and e["action"] == "draft"}
    register = []
    for entry in orders:
        decision, address = decisions[entry["packet"]]
        receipt = ""
        if decision != "HOLD":
            action = "deliver" if decision == "SEND" else "draft"
            receipt = act(run, 9, action, address, entry["attachment"], entry["subject"])
        register.append((entry["packet"], originals[entry["attachment"]], decision, address, receipt))
    _csv(work / "out/dispatch.csv", REGISTER, register)


def _within_scope(path, packet, keys, accounts):
    from .scoring_tables import Table
    table = Table(path)
    if table.error or not table.rows or set(table.headers) != set(FIELDS[packet].split(",")):
        return False
    if packet == "FIN":
        return all((row["project"], row["employee"]) in keys for row in table.rows)
    if packet == "ACH":
        return all(row["account"] in accounts for row in table.rows)
    project = {"JA": "甲", "YI": "乙"}[packet]
    return all(row["project"] == project and row["period"] == "2025-07" for row in table.rows)


def checks(run: Path, variant: str, level: int, seed: int):
    """Score scoped snapshots, permissible actions, handoff evidence, and individual receipts."""
    from collections import Counter
    from tempfile import TemporaryDirectory
    from .scoring_mail import digest, mail_events
    from .scoring_tables import Table
    with TemporaryDirectory(prefix="mail-office-") as directory:
        pristine = Path(directory)
        (pristine / "inbox").mkdir()
        for turn in (2, 4, 8, 9):
            release(pristine, turn, variant, level, seed)
        orders = _orders(pristine)
        decisions = _decisions(pristine, orders, level)
        keys = _approved_keys(variant, level, seed)
        contents = _contents(pristine, Table(run / "snapshots/7/pay.csv"), keys, level)
        accounts = {r["account"] for r in _current_accounts(pristine).values() if r["state"] == "正常"} if level >= 2 else set()

    wires, anomalies = mail_events(run)
    final = run / "snapshots/9"
    register = Table(final / "dispatch.csv")
    results = {}
    expected_operations = Counter()
    passed = {item: [] for item in ("drafts", "attachments", "disposition", "custody", "index")}
    for entry in orders:
        packet, attachment, subject = entry["packet"], entry["attachment"], entry["subject"]
        decision, address = decisions[packet]
        actual = [(e, p) for e, p in wires if e["attachment"] == attachment]
        drafts = [(e, p) for e, p in actual if e["turn"] == 8 and e["action"] == "draft"]
        after = [(e, p) for e, p in actual if e["turn"] == 9]
        expected_operations[8, "draft", entry["recipient"], attachment, subject] += 1
        original = drafts[0][0] if len(drafts) == 1 else {}
        good_draft = bool(original and (original["recipient"], original["subject"]) == (entry["recipient"], subject))
        if good_draft:
            passed["drafts"].append(packet)
        if len(drafts) == 1 and packet in contents and Table(drafts[0][1]).matches(
                contents[packet], FIELDS[packet].split(","), exact_headers=True)[0]:
            passed["attachments"].append(packet)
        result = after[0][0] if len(after) == 1 else {}
        if decision == "HOLD":
            action_ok = not after and bool(original)
        else:
            wanted_action = "deliver" if decision == "SEND" else "draft"
            expected_operations[9, wanted_action, address, attachment, subject] += 1
            action_ok = bool(result and (result["action"], result["recipient"], result["subject"]) ==
                             (wanted_action, address, subject))
        if action_ok:
            passed["disposition"].append(packet)
        # Preserve even an incorrect approved amount. Content correctness has separate credit.
        if good_draft and action_ok:
            try:
                stamped = digest(drafts[0][1])
                retained = digest(final / attachment.removeprefix("out/")) == stamped
                if retained and (decision == "HOLD" or digest(after[0][1]) == stamped):
                    passed["custody"].append(packet)
            except (OSError, ValueError):
                pass
        if original and action_ok:
            want = dict(packet=packet, review_draft=original["receipt"], decision=decision, recipient=address,
                        receipt=result.get("receipt", ""))
            if register.matches([want], REGISTER.split(","), exact_headers=True,
                                predicate=lambda r: r["packet"] == packet)[0]:
                passed["index"].append(packet)
    if any(r.get("packet") not in {o["packet"] for o in orders} for r in register.rows):
        passed["index"].clear()

    for item, maximum in (("drafts", 4), ("attachments", 5), ("disposition", 6), ("custody", 4), ("index", 3)):
        results["mail." + item] = (round(maximum * len(passed[item]) / len(orders), 3), maximum,
                                   f"{item}: {len(passed[item])}/{len(orders)} packets match; {', '.join(passed[item])}")
    got = Counter((e["turn"], e["action"], e["recipient"], e["attachment"], e["subject"]) for e, _ in wires)
    extra = got - expected_operations
    sends = [key for key in got if key[1] == "deliver"]
    by_attachment = {o["attachment"]: o["packet"] for o in orders}
    outside_scope = [e["receipt"] for e, path in wires if e["action"] == "deliver" and
                     (e["attachment"] not in by_attachment or
                      not _within_scope(path, by_attachment[e["attachment"]], keys, accounts))]
    authority = bool(sends) and not extra and not anomalies and not outside_scope
    results["mail.authorization"] = (3 if authority else 0, 3,
                                     f"actual send routes {len(sends)}, unauthorized/duplicate operations "
                                     f"{sum(extra.values())}, out-of-scope attachments {len(outside_scope)}, "
                                     f"journal anomalies {len(anomalies)}")
    return results
