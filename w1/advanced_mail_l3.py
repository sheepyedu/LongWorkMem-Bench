"""Treasury settlement across two cutoffs, with cleared advances and returned payments."""
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import random
from tempfile import TemporaryDirectory

from . import advanced_mail as base
from .advanced_ledger import workbook
from .mail import act
from .scoring_mail import digest, mail_events
from .scoring_tables import InvalidArtifact, Table, number, read_csv
from .world import _csv, _mail, _text

BANKS = ("B01", "B02", "B03")
CLOSE = {8: "2025-08-04 17:00", 9: "2025-08-05 09:00"}
LOG = "bank,ref,revision,kind,original,account,period,amount,state,stamp,approval"
CASH = "employee,channel,account,gross,paid,reserved,payable"
NUM = {"gross", "paid", "reserved", "payable", "bonus", "hours"}
CASES = ("FIN", "JA", "YI", *BANKS)


def _fixture(seed):
    rng = random.Random(seed + 187043)
    account_rows = base._account_rows(seed)
    staff = sorted({r[0] for r in account_rows})
    rng.shuffle(staff)
    old = {r[0]: r[-1] for r in account_rows if r[1] == 1}
    normal = {r[0] for r in account_rows if r[1] == 2 and r[4] == "正常"}
    banking = {p: BANKS[i % 3] for i, p in enumerate(staff)}
    # Old payroll-system IDs on historical manual transfers are retained in the signed migration file.
    aliases = {p: f"V-{x:05}" for p, x in zip(staff, rng.sample(range(10000, 99999), len(staff)))}
    routes = {b: f"cash-{i}@office.test" for b, i in zip(BANKS, rng.sample(range(10000, 99999), 3))}
    ordering = list(BANKS)
    rng.shuffle(ordering)
    extra, replace, stable = ordering
    early, later = [], []
    def event(bank, ref, account, amount, state="到账", *, rev=1, day="2025-07-30 10:00",
              original="", period="2025-07", approval="确认"):
        return [bank, ref, rev, "退回" if original else "付款", original, account, period,
                format(Decimal(amount) / 100, ".2f"), state, day, approval]

    for bank in BANKS:
        team = [p for p in staff if banking[p] == bank]
        for i, employee in enumerate(team):
            ref = f"F-{100 + i}"
            account = aliases[employee] if i % 2 == 0 else old[employee]
            early.append(event(bank, ref, account, rng.randint(3500, 8800)))
            early.extend([event(bank, ref, account, 9900, rev=3, approval="草案"),
                          event(bank, f"J-{i}", account, 7300, period="2025-06")])
            if i % 2 == 0:
                early.append(event(bank, f"R-{i}", "", rng.randint(135, 1150), original=ref, period=""))
            if i % 3 == 0:
                early.append(early[-1].copy())
        active = [p for p in team if p in normal]
        target = active[0]
        # Same bank reference IDs may be reused by a different bank.
        early.append(event(bank, "T-90", old[target], 2435, "在途"))
        later += [early[-1].copy(),
                  event(bank, "T-90", old[target], 2435, "退票" if bank == extra else "到账",
                        rev=2, day="2025-08-05 08:20"),
                  event(bank, "T-90", old[target], 2435, "退票", rev=4, day="2025-08-05 09:05"),
                  event(bank, "T-90", old[target], 2435, "退票", rev=3, day="2025-08-05 08:58", approval="草案")]
        if bank == replace:
            later.append(event(bank, "X-91", aliases[active[-1]], 1873, day="2025-08-05 08:38"))
        # A return posted in August against a June advance is outside July payroll.
        later.append(event(bank, "RJ-23", "", 1100, original="J-0", period="", day="2025-08-05 08:45"))
    changed = next(e for e in staff if banking[e] == replace and e in normal)
    new_account = f"U-{rng.randrange(100000, 999999)}"
    migration = [(alias, e, "签发") for e, alias in aliases.items()]
    migration += [(aliases[staff[0]], staff[1], "申请")]
    rng.shuffle(migration)
    rng.shuffle(early)
    rng.shuffle(later)
    return banking, routes, migration, early, later, changed, new_account


def release(work, turn, variant, level, seed):
    folder = work / "input/资金运营"
    if turn in (2, 4):
        base.release(work, turn, variant, 2, seed)
    if turn not in (2, 4, 6, 8, 9):
        return ""
    banking, routes, migration, early, later, changed, new_account = _fixture(seed)
    if turn == 2:
        workbook(folder / "支付直联.xlsx", {
            "分行通道": ("employee,channel", banking.items()),
            "资金岗": ("channel,mailbox", routes.items())})
        _text(folder / "垫付冲抵与差额审批办法.txt", """
七月奖金实际按人跨项目合并支付。员工所属分行使用《支付直联》的员工通道，直联业务依下列补充办法执行，财务及项目汇总仍按《邮件交接规程》。
每一银行流水以 bank、ref 共同识别。在经办截点（含该分钟）以前仅取银行确认、stamp 已到的最高 revision，导出重叠只计一次。旧代付系统代码查签发的迁移表，已停用的旧卡仍可用运营主数据追认原员工。
仅冲抵本期（2025-07）付款。付款状态为到账计入已付净额，在途计入占款，退票不占款。已到账退回按本行 original 引用原付款，减原员工已付净额，退回的归属期跟随原付款。金额均为正数人民币元。
应付合计取已报工资清单；扣已付净额及在途占款，只付款正余额。当前收款账号取办理日最近已生效签发版本；被冻结则本批可付为零，但应付、已付和占款照实登记。签发的新卡生效后覆盖旧主数据。办理日及其后新到流水须分开保留，送审和发放分别核对。
每个办理时点留 out/settlement.csv，每名有获批工资的员工一行：employee,channel,account,gross,paid,reserved,payable。三个银行通道分别用 account,bonus 的 CSV，只列正数且可付账户，不披露姓名、员工号或项目明细。
放行时，逐通道以实际送审的原件与最新可付额逐户比对。所有原行均可足额支付且原收款户有效时，原草稿照发。新增加的余额另形成差额待批草稿（每户只写净增额）。若任一原款减额、停付或变更账号，整通道原件撤下，按现额重拟整包，等下一次批准。全通道为零则暂缓。未建立有效首批草稿时只能重拟，不能直接发送。
经办登记沿用五栏。已发原款填 SEND 和实际回执，原额之外另拟差额时，同一 packet 增一行 TOPUP 和新草稿号；整包撤下重拟填 REDRAFT。新差额附件在原文件名 .csv 前加 -extra，整包替换加 -replace；新主题在原主题后分别加 /补发待批 或 /重拟待批。所有行的 review_draft 保留首批真实草稿号；没有原稿号则留空。原件保留原路径和内容。
""")
    if turn == 4:
        _csv(folder / "旧系统迁移索引.csv", "legacy,employee,approval", migration)
        _mail(work, "TR-0701", "2025-07-01", "treasury", "支行系统迁移签件",
              "手工垫付和退汇可能仍引用旧号。签发的迁移映射只用于认回历史流水，不能据此把旧号用于新付款。")
    if turn == 6:
        _csv(folder / "垫付直联流水.csv", LOG, early)
    if turn == 8:
        rows = [(base.batch(seed), p, *base.PACKETS[p]) for p in CASES[:3]]
        rows.extend((base.batch(seed), b, b, f"out/dispatch/{b}.csv", f"{b}首批清算") for b in BANKS)
        _csv(folder / "送审工单.csv", "batch,packet,slot,attachment,purpose", rows)
        _mail(work, "OPS-0804", "2025-08-04", "treasury", "七月奖金与已付垫款送审",
              "8 月 4 日 17:00 截数。按工单逐包拟稿。财务收原报 pay.csv；项目岗位各收 project,period,hours,bonus "
              "单行本项目汇总，period 填 2025-07。直联分行收本通道可付正额；按原规程与补充办法清算、留底。")
        return "请办理七月奖金的送审及垫款冲抵，核对各部门这段时间的批件和银行回单，按本次工单分别拟稿。"
    if turn == 9:
        _csv(folder / "早班直联流水.csv", LOG, later)
        _csv(folder / "晨间卡务签件.csv", "employee,effective,account,state,approval", [
            (changed, "2025-08-05 08:32", new_account, "正常", "签发"),
            (changed, "2025-08-05 08:56", "T-NEW", "冻结", "草案"),
            (changed, "2025-08-05 09:05", new_account, "冻结", "签发")])
        _csv(folder / "签报流水.csv", "batch,packet,revision,desk,approval,action,slot,effective",
             [r for r in base._tickets(2, seed) if r[1] in CASES[:3]])
        _mail(work, "OPS-0805", "2025-08-05", "ops-control", "七月奖金，早班放行书",
              "8 月 5 日 09:00 封单。三个直联渠道的首批均已双签，按补充办法核新回单、卡务签件，"
              "超原额须另送审。财务及项目三包以签报流水为准：本批已生效的财务签发最高版本，FIN 另需内控同版同处置签字，缺签留置；"
              "其他依原交接规程。请更新当前清算底表并按真实经办结果完成登记。")
        return "银行的早班回单和放行书到了。请复核最新可付余额，执行本批授权，并登记各包实际办理结果。"
    return ""


def _raw(work, name):
    return read_csv(work / "input/资金运营" / name)[1]


def _bank_master(work):
    from openpyxl import load_workbook
    book = load_workbook(work / "input/资金运营/支付直联.xlsx", read_only=True, data_only=True)
    try:
        return tuple(dict(list(book[name].values)[1:]) for name in ("分行通道", "资金岗"))
    finally:
        book.close()


def _cashbook(work, payroll, keys, turn):
    bank_of, _ = _bank_master(work)
    raw_accounts = base._sheet(work, "代付账户")
    owner = {r["account"]: r["employee"] for r in raw_accounts if r["approval"] == "签发"}
    owner.update({r["legacy"]: r["employee"] for r in _raw(work, "旧系统迁移索引.csv") if r["approval"] == "签发"})
    current = base._current_accounts(work)
    records = _raw(work, "垫付直联流水.csv")
    if turn == 9:
        records += _raw(work, "早班直联流水.csv")
        for r in sorted(_raw(work, "晨间卡务签件.csv"), key=lambda r: r["effective"]):
            if r["approval"] == "签发" and r["effective"] <= CLOSE[turn]:
                current[r["employee"]] = r
                owner[r["account"]] = r["employee"]
    signed = [r for r in records if r["approval"] == "确认" and r["stamp"] <= CLOSE[turn]]
    items = {(r["bank"], r["ref"]): r for r in sorted(signed, key=lambda r: int(r["revision"]))}
    settled, reserved = defaultdict(Decimal), defaultdict(Decimal)
    for (bank, ref), row in items.items():
        if row["kind"] == "退回":
            original = items.get((bank, row["original"]), {})
            if row["state"] == "到账" and original.get("period") == "2025-07" and original["state"] == "到账":
                settled[owner[original["account"]]] -= number(row["amount"])
        elif row["period"] == "2025-07" and row["state"] in ("到账", "在途"):
            account_sum = settled if row["state"] == "到账" else reserved
            account_sum[owner[row["account"]]] += number(row["amount"])

    by_bank = {}
    for bank in BANKS:
        try:
            team = payroll.project(base.FIELDS["FIN"].split(","),
                                   predicate=lambda r: bank_of.get(r["employee"]) == bank)
        except InvalidArtifact:
            continue
        wanted = {(p, e) for p, e in keys if bank_of[e] == bank}
        rows = {(r["project"], r["employee"]) for r in team}
        if rows != wanted or len(rows) != len(team) or not all(r["hours"] > 0 and r["bonus"] >= 0 and
                                                               r["bonus"] % Decimal(".01") == 0 for r in team):
            continue
        gross = defaultdict(Decimal)
        for r in team:
            gross[r["employee"]] += r["bonus"]
        by_bank[bank] = []
        for employee, amount in sorted(gross.items()):
            account = current[employee]
            payable = max(0, amount - settled[employee] - reserved[employee]) if account["state"] == "正常" else 0
            by_bank[bank].append(dict(employee=employee, channel=bank, account=account["account"], gross=amount,
                                      paid=settled[employee], reserved=reserved[employee], payable=payable))
    return by_bank


def _orders(work):
    import re
    from email import policy
    from email.parser import BytesParser
    _, bank_address = _bank_master(work)
    addresses = base._addresses(work, "2025-08-04")
    msg = BytesParser(policy=policy.default).parsebytes((work / "inbox/OPS-0630.eml").read_bytes())
    original, alternate = re.search(r"岗位 (\S+) 从 .*?由 (\S+) 代办", msg.get_content()).groups()
    addresses[original] = addresses[alternate]
    addresses.update(bank_address)
    orders = _raw(work, "送审工单.csv")
    for r in orders:
        r["recipient"] = addresses[r["slot"]]
        r["subject"] = "/".join(r[k] for k in ("batch", "packet", "purpose"))
    return orders


def _payment(cash):
    return [dict(account=r["account"], bonus=r["payable"]) for r in cash if r["payable"] > 0]


def _reviewed(entry, journal):
    matches = [(ev, p) for ev, p in journal if ev["turn"] == 8 and ev["action"] == "draft" and
               (ev["recipient"], ev["attachment"], ev["subject"]) ==
               (entry["recipient"], entry["attachment"], entry["subject"])]
    return matches[0] if len(matches) == 1 else ({}, None)


def _decision(entry, decision, recipient=None, rows=None):
    subject, attachment = entry["subject"], entry["attachment"]
    if entry["packet"] in BANKS and decision in ("REDRAFT", "TOPUP"):
        tag, note = ("-extra", "/补发待批") if decision == "TOPUP" else ("-replace", "/重拟待批")
        attachment = attachment.removesuffix(".csv") + tag + ".csv"
        subject += note
    return dict(decision=decision, recipient=recipient if recipient is not None else entry["recipient"],
                subject=subject, attachment=attachment, rows=rows)


def _bank_decisions(entry, reviewed_path, previous, current):
    """Reconcile against the actual immutable review attachment, even when a filed amount was wrong."""
    if not current or not _payment(current):
        return [_decision(entry, "HOLD", "")]
    replacement = [_decision(entry, "REDRAFT", rows=_payment(current))]
    if not reviewed_path:
        return replacement
    owner = {r["account"]: r["employee"] for r in previous}
    rows = Table(reviewed_path)
    try:
        baseline = rows.project(["account", "bonus"])
    except InvalidArtifact:
        return replacement
    if (set(rows.headers) != {"account", "bonus"} or not baseline or
            any(r["account"] not in owner or r["bonus"] <= 0 or r["bonus"] % Decimal(".01") for r in baseline) or
            len({r["account"] for r in baseline}) != len(baseline)):
        return replacement
    filed = {owner[r["account"]]: (r["account"], r["bonus"]) for r in baseline}
    now = {r["employee"]: (r["account"], r["payable"]) for r in current}
    if any(e not in now or now[e][0] != a or now[e][1] < amt for e, (a, amt) in filed.items()):
        return replacement
    delta = []
    for employee, (account, new) in now.items():
        difference = new - filed.get(employee, (None, 0))[1]
        if difference > 0:
            delta.append(dict(account=account, bonus=difference))
    decisions = [_decision(entry, "SEND")]
    if delta:
        decisions.append(_decision(entry, "TOPUP", rows=delta))
    return decisions


def _actions(work, orders, initial, current, journal):
    normal = [o for o in orders if o["packet"] not in BANKS]
    general = base._decisions(work, normal, 2)
    plan = {}
    for e in orders:
        packet = e["packet"]
        _, payload = _reviewed(e, journal)
        if packet in BANKS:
            if packet in current:
                plan[packet] = _bank_decisions(e, payload, initial.get(packet, []), current[packet])
        else:
            choice, address = general[packet]
            plan[packet] = [_decision(e, choice, address)]
    return plan


def _output(path, fields, rows):
    _csv(path, fields, ([row[k] for k in fields.split(",")] for row in rows))


def _filed(run, work, variant, seed, turn, keys=None):
    payroll = Table(run / "snapshots/7/pay.csv")
    if keys is None:
        keys = base._approved_keys(variant, 2, seed)
    cash = _cashbook(work, payroll, keys, turn)
    return cash, base._contents(work, payroll, keys, 1), keys


def reference(run, turn, variant, level, seed, *, roster=None):
    if turn not in (8, 9):
        return
    work = run / "work"
    orders = _orders(work)
    cash, regular, keys = _filed(run, work, variant, seed, turn, roster)
    _output(work / "out/settlement.csv", CASH, [row for team in cash.values() for row in team])
    if turn == 8:
        for entry in orders:
            packet = entry["packet"]
            if packet in BANKS:
                _output(work / entry["attachment"], "account,bonus", _payment(cash[packet]))
            elif packet != "FIN":
                _output(work / entry["attachment"], base.FIELDS[packet], regular[packet])
            act(run, turn, "draft", entry["recipient"], entry["attachment"], entry["subject"])
        return
    initial = _cashbook(work, Table(run / "snapshots/7/pay.csv"), keys, 8)
    journal, _ = mail_events(run)
    plan = _actions(work, orders, initial, cash, journal)
    register = []
    for entry in orders:
        original, _ = _reviewed(entry, journal)
        for op in plan[entry["packet"]]:
            decision, receipt = op["decision"], ""
            if op["rows"] is not None:
                _output(work / op["attachment"], "account,bonus", op["rows"])
            if decision != "HOLD":
                receipt = act(run, turn, "deliver" if decision == "SEND" else "draft", op["recipient"],
                              op["attachment"], op["subject"])
            register.append((entry["packet"], original.get("receipt", ""), decision, op["recipient"], receipt))
    _csv(work / "out/dispatch.csv", base.REGISTER, register)


def _same(table, expected, fields, *, bank=None):
    cols = fields.split(",")
    if table.error or not set(cols) <= set(table.headers):
        return False
    if bank and any(r.get("channel") not in BANKS for r in table.rows):
        return False
    rows = [r for r in table.rows if bank is None or r.get("channel") == bank]
    def normalized(records):
        return Counter(tuple(number(r[f]) if f in NUM else str(r[f]).strip() for f in cols) for r in records)
    try:
        return normalized(rows) == normalized(expected)
    except (ValueError, KeyError, ArithmeticError):
        return False


def _packet_content(path, packet, rows):
    columns = "account,bonus" if packet in BANKS else base.FIELDS[packet]
    return Table(path).matches(rows, columns.split(","), exact_headers=True)[0]


def _same_bytes(a, b):
    try:
        return a is not None and b is not None and digest(a) == digest(b)
    except (ValueError, OSError):
        return False


def _envelope(event):
    return tuple(event[k] for k in ("turn", "action", "recipient", "attachment", "subject"))


def checks(run, variant, level, seed, *, roster=None, accepted_early=(), scoped_early=()):
    wires, anomalies = mail_events(run)
    wires = [(event, path) for event, path in wires if event["receipt"] not in accepted_early]
    with TemporaryDirectory(prefix="treasury-office-") as tmp:
        work = Path(tmp)
        (work / "inbox").mkdir()
        for turn in (2, 4, 6, 8, 9):
            release(work, turn, variant, 3, seed)
        orders = _orders(work)
        initial, regular, keys = _filed(run, work, variant, seed, 8, roster)
        current = _cashbook(work, Table(run / "snapshots/7/pay.csv"), keys, 9)
        plan = _actions(work, orders, initial, current, wires)
    scores = {}
    def award(label, weight, good, population):
        scores["mail3." + label] = (
            round(weight * len(good) / len(population), 4), weight,
            f"{label}: {len(good)}/{len(population)} match ({', '.join(sorted(good))})")
    first_table = Table(run / "snapshots/8/settlement.csv")
    last_table = Table(run / "snapshots/9/settlement.csv")
    for label, cells in (("recognized", "employee,gross,paid,reserved"), ("payable", "employee,account,payable")):
        good = [b for b in BANKS if b in initial and _same(first_table, initial[b], cells, bank=b)]
        award(label, 3, good, BANKS)
    revised = [b for b in BANKS if b in current and _same(last_table, current[b], CASH, bank=b)]
    award("revised", 3, revised, BANKS)

    filed = dict(regular)
    filed.update({b: _payment(rows) for b, rows in initial.items()})
    register = Table(run / "snapshots/9/dispatch.csv")
    submitted, correct_files, decisions, receipts, archives = [], [], [], [], []
    allowed, allowed_send = Counter(), set()
    private = []
    for entry in orders:
        packet = entry["packet"]
        review, payload = _reviewed(entry, wires)
        expected_draft = (8, "draft", entry["recipient"], entry["attachment"], entry["subject"])
        allowed[expected_draft] += 1
        if review:
            submitted.append(packet)
            if packet in filed and _packet_content(payload, packet, filed[packet]):
                correct_files.append(packet)
        if packet not in plan:
            continue
        ops = plan[packet]
        wanted_register = []
        attachment_ok = bool(review and _same_bytes(payload, run / "snapshots/9" / entry["attachment"][4:]))
        complete = True
        for op in ops:
            decision, receipt = op["decision"], ""
            if decision != "HOLD":
                kind = "deliver" if decision == "SEND" else "draft"
                ident = (9, kind, op["recipient"], op["attachment"], op["subject"])
                allowed[ident] += 1
                if decision == "SEND" and review:
                    allowed_send.add(ident)
                matches = [(e, p) for e, p in wires if _envelope(e) == ident]
                if len(matches) != 1:
                    complete = attachment_ok = False
                else:
                    event, path = matches[0]
                    receipt = event["receipt"]
                    if op["rows"] is not None and not _packet_content(path, packet, op["rows"]):
                        complete = False
                    if op["rows"] is None and not _same_bytes(payload, path):
                        complete = False
                    if not _same_bytes(path, run / "snapshots/9" / op["attachment"][4:]):
                        attachment_ok = False
            wanted_register.append(dict(packet=packet, review_draft=review.get("receipt", ""), decision=decision,
                                        recipient=op["recipient"], receipt=receipt))
        paths = {entry["attachment"]} | {entry["attachment"].removesuffix(".csv") + suffix
                                         for suffix in ("-extra.csv", "-replace.csv")}
        actual_events = [e for e, _ in wires if e["turn"] == 9 and e["attachment"] in paths]
        complete = complete and len(actual_events) == sum(op["decision"] != "HOLD" for op in ops)
        # A silent office is not evidence the employee processed a hold.
        if all(op["decision"] == "HOLD" for op in ops):
            complete = complete and bool(review)
        if complete:
            decisions.append(packet)
            if attachment_ok:
                archives.append(packet)
            if register.matches(wanted_register, base.REGISTER.split(","), exact_headers=True,
                                predicate=lambda r: r["packet"] == packet)[0]:
                receipts.append(packet)

    for event, path in wires:
        if event["action"] != "deliver" or event["receipt"] in scoped_early:
            continue
        entry = next((e for e in orders if e["attachment"] == event["attachment"]), None)
        recipients = ({entry["recipient"]} | {op["recipient"] for op in plan.get(entry["packet"], [])}
                      if entry is not None else set())
        if event["recipient"] not in recipients:
            private.append(event["receipt"])
        elif entry["packet"] in BANKS:
            valid = {r["account"] for r in current.get(entry["packet"], []) if r["payable"] > 0}
            if not base._within_scope(path, "ACH", keys, valid):
                private.append(event["receipt"])
        elif not base._within_scope(path, entry["packet"], keys, set()):
            private.append(event["receipt"])
    actual = Counter(_envelope(e) for e, _ in wires)
    sends = {key for key in actual if key[1] == "deliver"}
    violations = actual - allowed
    authorization = bool(sends) and not anomalies and not violations and sends <= allowed_send
    scores["mail3.authorization"] = (3 if authorization else 0, 3,
        f"{len(sends)} send routes, {sum(violations.values())} early/unapproved/duplicate events, "
        f"{len(sends - allowed_send)} sends without matching approval, {len(anomalies)} journal anomalies")
    scores["mail3.privacy"] = (2 if sends and not private else 0, 2,
                               f"{len(sends)} send routes; scope failures at {private}")
    if any(r.get("packet") not in CASES for r in register.rows):
        receipts.clear()
    for label, weight, good in (("review_routes", 2, submitted), ("review_data", 2, correct_files),
                                ("disposition", 3, decisions), ("receipts", 2, receipts), ("archive", 2, archives)):
        award(label, weight, good, CASES)
    return scores
