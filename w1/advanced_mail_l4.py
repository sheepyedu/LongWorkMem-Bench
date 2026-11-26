"""Inquiry correspondence linked to signed AP cases, actual mailbox receipts, and bank returns."""
from collections import Counter
import random

from . import advanced_mail_l3 as treasury
from .mail import act
from .scoring_mail import mail_events
from .scoring_tables import Table, number
from .world import _csv, _mail

EARLY = (2, 5, 6)
STAGES = {2: "首询", 5: "续核", 6: "银核"}
INDEX = "stage,desk,recipient,prior,receipt"
SITES = ("江东", "江北", "南港", "西港")


def _desks(seed):
    rng = random.Random(f"W1-case-correspondence/{seed}")
    sites = rng.sample(SITES, 2)
    desks = {}
    for site in sites:
        current, delegate = rng.sample(range(1000, 9999), 2)
        desks[site] = (f"ap-{current}@office.test", f"delegate-{delegate}@office.test")
    return desks, rng.choice(sites), rng.sample(list(treasury.BANKS), 2)


def _requests(seed):
    """Registered supplier inquiries concern real unmapped source invoices common to all four sites."""
    desks, _, banks = _desks(seed)
    payment_rows = treasury._fixture(seed)[3]
    cases, retained = {}, {}
    for i, site in enumerate(desks):
        # These source IDs are present in the signed June invoice registers in both worlds.
        cases[site] = [dict(site=site, id=f"V{n}", po=f"迁-{n}", line=str(1 + (n - 1) % 2))
                       for n in (6, 29, 52)]
        retained[site] = cases[site][i + 1:]
    return cases, retained, banks, payment_rows


def release(work, turn, variant, level, seed):
    prompt = treasury.release(work, turn, variant, 3, seed)
    folder = work / "input/核验往来"
    desks, redirect, banks = _desks(seed)
    cases, retained, _, _ = _requests(seed)
    if turn == 2:
        rows = [(site, row["id"], "invoice", "签发") for site, items in cases.items() for row in items]
        # One signed request has already matched its purchase order. Its file must stay at the desk.
        rows += [(site, "I5", "invoice", "签发") for site in desks]
        rows += [(site, "U6", "receipt", "提议") for site in desks]
        rows += [(site, "V6", "invoice", "提议") for site in SITES if site not in desks]
        _csv(folder / "供应商询证授权.csv", "site,id,source,approval", rows)
        _csv(folder / "应付函证岗位.csv", "site,mailbox", ((s, a[0]) for s, a in desks.items()))
        _mail(work, "AP-0630", "2025-06-30", "ap-control", "今日关账首询，批准发函",
              "仅今日实际发函。将供应商签发的询证授权与六月截至今日仍待认领的凭证交叉核实。每个获准库区分发一封到应付函证岗位，"
              "只附本库区对应发票 site,id,po,line（原载引用），不附金额、仓储及其他库区。首询主题 核验/首询/库区，"
              "附件 out/verify/首询-库区.csv，主题和路径中的库区替换为实际名称。核验均直接投递，无需先拟稿。"
              "往来累计台账 out/verify_index.csv 栏位 stage,desk,recipient,prior,receipt，stage 填首询/续核/银核，"
              "desk 用库区或支行号，prior 为对应前函真实发送回执（首次为空），receipt 为本次真实发送回执。"
              "每次发送后更新台账，附件原件留存至最终归档；错过窗口不补发旧函。")
    if turn == 5:
        claims = []
        for site, rows in cases.items():
            stay = {r["id"] for r in retained[site]}
            for row in rows:
                claims.extend([(site, row["id"], 1, "继续", "签发", "2025-07-02"),
                               (site, row["id"], 2, "继续" if row["id"] in stay else "销询", "签发", "2025-07-08"),
                               (site, row["id"], 3, "销询", "草案", "2025-07-08"),
                               (site, row["id"], 4, "销询", "签发", "2025-07-09")])
        _csv(folder/"供应商补件回函.csv", "site,id,revision,action,status,effective", claims)
        _csv(folder/"函证临时代理.csv", "site,effective,status,mailbox", [
            (redirect, "2025-07-08", "签发", desks[redirect][1]),
            (redirect, "2025-07-09", "签发", "later@office.test"),
            (next(s for s in desks if s != redirect), "2025-07-08", "提议", "proposed@office.test")])
        _mail(work, "AP-0708", "2025-07-08", "ap-control", "今日续核授权及供应商回函",
              "本次回函仅用于函证跟进。按 7 月 8 日（含）前签发且已生效的最高数字 revision 处理每项首询授权。"
              "销询不再跟进，继续项按库区合并发一封到当日获签代理或原岗位。附件仅 prior,site,id,po,line，"
              "prior 引用该库区六月实际首询发送回执。若缺少唯一有效的首询（正确主题、附件名、收件方且实际只发送一次），"
              "并入本次补救，prior 留空，不补发六月函。主题 核验/续核/库区，文件 out/verify/续核-库区.csv。"
              "按首询规程累计台账并保留前函。")
    if turn == 6:
        _csv(folder/"资金抽核委托.csv", "bank,scope,approval", [(b, "占款与退回", "签发") for b in banks] +
             [(b, "全部流水", "申请") for b in treasury.BANKS])
        _mail(work, "TR-0731", "2025-07-31", "treasury", "月末资金抽核，今日直发",
              "仅向资金抽核委托中获签的支行发函，地址查支付直联资金岗。按垫付直联流水在 7 月 31 日 17:00 的"
              "已确认有效版本，一行一个银行流水，列本期在途付款，以及已到账且引用本期已到账付款的退回（不得抄送其他分行）。"
              "不附员工和卡号，仅列 bank,ref,original,amount，付款 original 留空，amount 取该笔原正数元额。"
              "按支行各发一封，主题 核验/银核/支行号，附件 out/verify/银核-支行号.csv；首次银核 prior 为空。"
              "一并更新累计台账，原件均保留。")
    if turn == 9:
        _mail(work, "AP-0805", "2025-08-05", "ap-control", "核验往来归档",
              "请同时核对累计核验台账和三次窗口实际传出的附件，核验工单均已截止，按原件与真实回执归档。")
    return prompt


def _envelope(turn, desk, recipient):
    stage = STAGES[turn]
    return (turn, "deliver", recipient, f"out/verify/{stage}-{desk}.csv", f"核验/{stage}/{desk}")


def _unique(journal, envelope):
    hits = [(event, path) for event, path in journal if treasury._envelope(event) == envelope]
    return hits[0] if len(hits) == 1 else ({}, None)


def _orders(seed, turn, journal):
    desks, redirect, banks = _desks(seed)
    cases, retained, _, payment_rows = _requests(seed)
    if turn == 2:
        return {s: (_envelope(2, s, a[0]), "site,id,po,line", cases[s], "") for s,a in desks.items()}
    if turn == 5:
        orders = {}
        for site, addr in desks.items():
            event, _ = _unique(journal, _envelope(2, site, addr[0]))
            prior = event.get("receipt", "")
            envelope = _envelope(5, site, addr[1] if site == redirect else addr[0])
            orders[site] = envelope, "prior,site,id,po,line", [dict(r, prior=prior) for r in retained[site]], prior
        return orders
    routes = treasury._fixture(seed)[1]
    versions = {}
    for bank, ref, rev, kind, orig, account, period, amount, state, stamp, approval in payment_rows:
        if approval == "确认" and stamp <= "2025-07-31 17:00":
            key = bank, ref
            if key not in versions or rev > versions[key][0]:
                versions[key] = rev, kind, orig, period, amount, state
    orders = {}
    for bank in banks:
        rows = []
        for (channel, ref), (_, kind, orig, period, amount, state) in versions.items():
            if channel != bank:
                continue
            if kind == "退回":
                original = versions.get((bank, orig))
                keep = original and state == "到账" and original[3] == "2025-07" and original[5] == "到账"
            else:
                keep = state == "在途" and period == "2025-07"
            if keep:
                rows.append(dict(bank=bank, ref=ref, original=orig, amount=amount))
        orders[bank] = _envelope(6, bank, routes[bank]), "bank,ref,original,amount", rows, ""
    return orders


def _roster(variant, seed):
    from .advanced_pay_l4 import expected_pay
    return {(row["project"], row["employee"]) for row in expected_pay(variant, 4, seed)}


def reference(run, turn, variant, level, seed):
    if turn not in EARLY:
        if turn in (8, 9):
            treasury.reference(run, turn, variant, 3, seed, roster=_roster(variant, seed))
        return
    work = run / "work"
    journal, _ = mail_events(run)
    index = Table(work / "out/verify_index.csv").rows
    for desk, (envelope, fields, rows, prior) in _orders(seed, turn, journal).items():
        _, _, recipient, attachment, subject = envelope
        treasury._output(work / attachment, fields, rows)
        receipt = act(run, turn, "deliver", recipient, attachment, subject)
        index.append(dict(stage=STAGES[turn], desk=desk, recipient=recipient, prior=prior, receipt=receipt))
    treasury._output(work / "out/verify_index.csv", INDEX, index)


def _data_ok(path, fields, rows, *, scope=False, valid_prior=()):
    """Allow currency formatting while rejecting extra fields, records, or leaked cell text."""
    table = Table(path)
    cols = fields.split(",")
    if table.error or not table.rows or set(table.headers) != set(cols):
        return False

    def normalize(r):
        result = []
        for field in cols:
            value = r[field]
            if field == "prior" and scope and value in valid_prior:
                value = None
            if field in ("amount", "line"):
                value = number(value)
                if scope and field == "amount":
                    # The signed bank's own line can be in error without disclosing someone else's data.
                    value = None
            result.append(value)
        return tuple(result)

    try:
        sent = Counter(normalize(row) for row in table.rows)
        requested = Counter(normalize(row) for row in rows)
        return not (sent - requested) if scope else sent == requested
    except (ValueError, KeyError):
        return False


LATE = {"recognized": 1.5, "payable": 1.5, "review_routes": 1, "review_data": 1,
        "revised": 1.5, "disposition": 1.5, "authorization": 2, "privacy": 1,
        "receipts": 1.5, "archive": 1.5}


def checks(run, variant, level, seed):
    journal, _ = mail_events(run)
    accepted, scoped = set(), set()
    results = {}
    final = run / "snapshots/9"
    milestones = list(EARLY) + [9]
    # Follow actual send receipts across each subsequent checkpoint; never accept a volunteered receipt ID.
    indices = {t: Table(run / "snapshots" / str(t) / "verify_index.csv") for t in milestones}
    expected_by_stage = {}
    for turn, weight in ((2, 3), (5, 4), (6, 4)):
        orders = _orders(seed, turn, journal)
        expected_by_stage[STAGES[turn]] = set(orders)
        route, contents, archives = [], [], []
        for desk, (envelope, fields, rows, prior) in orders.items():
            valid_prior = {""}
            if turn == 5:
                first_route = _orders(seed, 2, journal)[desk][0]
                valid_prior.update(e["receipt"] for e, _ in journal if treasury._envelope(e) == first_route)
            for event, payload in journal:
                if (treasury._envelope(event)[1:] == envelope[1:] and
                        _data_ok(payload, fields, rows, scope=True, valid_prior=valid_prior)):
                    scoped.add(event["receipt"])
            event, payload = _unique(journal, envelope)
            if not event:
                continue
            route.append(desk)
            if event["receipt"] in scoped:
                accepted.add(event["receipt"])
            if _data_ok(payload, fields, rows):
                contents.append(desk)
            want = dict(stage=STAGES[turn], desk=desk, recipient=event["recipient"],
                        prior=prior, receipt=event["receipt"])
            if (all(table.matches([want], INDEX.split(","), exact_headers=True,
                                  predicate=lambda r: r["stage"] == want["stage"] and r["desk"] == desk)[0]
                    for t, table in indices.items() if t >= turn) and
                    treasury._same_bytes(payload, final / envelope[3][4:])):
                archives.append(desk)
        for label, credit, good in (("route", 1, route), ("content", weight - 2, contents), ("record", 1, archives)):
            results[f"mail4.r{turn}_{label}"] = (credit * len(good) / len(orders), credit,
                                                f"{len(good)}/{len(orders)} desks: {', '.join(good)}")
    for turn, table in indices.items():
        permitted = {STAGES[t]: expected_by_stage[STAGES[t]] for t in EARLY if t <= turn}
        if any(row.get("desk") not in permitted.get(row.get("stage"), set()) for row in table.rows):
            for t in EARLY:
                if t <= turn:
                    results[f"mail4.r{t}_record"] = (0, 1, f"extra or unrecognized entry in R{turn} index")
    late = treasury.checks(run, variant, 3, seed, roster=_roster(variant, seed), accepted_early=accepted, scoped_early=scoped)
    for full_label, (points, maximum, reason) in late.items():
        label = full_label.split(".")[-1]
        weight = LATE[label]
        results["mail4." + label] = (round(weight * points / maximum, 4), weight, reason)
    return results
