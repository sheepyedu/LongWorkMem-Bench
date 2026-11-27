"""Quarter-to-date incentive settlement and jointly approved transfers of clock tickets."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import random
from tempfile import TemporaryDirectory

from . import advanced_pay_checks as payroll
from . import advanced_pay_l3 as migration
from .advanced_pay import staff
from .reference import PAY, read_csv, write_csv
from .scoring_tables import Table
from .world import _csv, _mail, _text


CARRY = Path("input/财务会签/六月激励结转.csv")
PROPOSALS = Path("input/人事值班/追溯调班登记.csv")
STAMPS = Path("input/财务会签/调班联签流水.csv")
ORDER_FIELDS = ("site", "ticket", "revision", "destination", "percent")
CUTOFF = "2025-08-03 18:00"


def quarter_records(work, seed):
    rand = random.Random(seed + 7430)
    rows = []
    for project in "甲乙":
        for employee in staff(2):
            carry = Decimal(rand.randrange(8, 246)) / 4
            rows.extend([(project, employee, 1, carry + 6, "签发", "2025-06-24 09:00"),
                         (project, employee, 2, carry, "签发", "2025-06-30 18:00")])
            if rand.randrange(3) == 0:
                rows.extend([(project, employee, 3, 0, "试算", "2025-06-30 16:00"),
                             (project, employee, 4, carry + 11, "签发", "2025-07-01 08:00")])
    rand.shuffle(rows)
    _csv(work / CARRY, "project,employee,revision,prior_hours,decision,signed", rows)


def generate_orders(seed):
    rand = random.Random(seed + 1944)
    proposals, stamps = [], []
    for index in range(556):
        # Include pending tickets, as well as the same local ticket number in both plants.
        if index % 53 != 2 and index % 17 not in (1, 2, 7, 8, 12):
            continue
        site, ticket = ("东厂", "西厂")[index % 2], f"T-{1001 + index // 2}"
        target = rand.choice("甲乙丙")
        qty = rand.choice([25, 50, 75, 100])
        if index % 53 == 2:
            qty = 100 if index % 2 == 0 else 50
        for rev, status, dest, pct in [(1, "改派", target, qty), (2, "撤回" if index % 5 == 0 else "改派",
                                    "乙" if target == "甲" else "甲", 100 if qty < 100 else 50)]:
            proposals.append([site, ticket, rev, dest, pct, status])
            for authority in ("人事", "财务"):
                signed = "2025-08-02 17:00" if rev == 1 else CUTOFF
                decision = "签发"
                if rev == 2 and authority == "财务":
                    if index % 4 == 0:
                        signed = "2025-08-03 18:04"
                    elif index % 4 == 1:
                        decision = "草拟"
                stamps.append([site, ticket, rev, authority, decision, signed])
        # An unapproved older duplicate in the combined export does not void the signed stamp.
        if index % 8 == 1:
            stamps.append([site, ticket, 1, "财务", "草拟", "2025-08-02 09:15"])
    rand.shuffle(proposals)
    rand.shuffle(stamps)
    return proposals, stamps


def release(work, turn, variant, level, seed):
    prompt = migration.release(work, turn, variant, 3, seed)
    if turn == 4:
        quarter_records(work, seed)
        _text(work / "input/薪酬制度/激励季度合同-六月版.txt", """
财务、人事联签的激励合同。公司以六月至八月作为本期激励季度。
项目按员工分别结转。六月已结的 prior_hours 按(项目,员工)取 6 月 30 日 18:00（含）以前签发的最高完整版本，七月结算冻结该数。
本期奖金只分七月净池。季度累计计薪工时前 40 小时（含）每小时折一份，超出部分每小时折一份半。七月份额=六月与七月合计的累计份额减六月已结累计份额。例：六月 38 小时，七月 6 小时，则七月份额为 2+4×1.5=8 份；六月 44 小时、七月 2 小时则为 3 份。
按各人本月增量份额比例分本项目奖金，合同上限、再分和分币沿用已签条款。尾差优先者按本月增量份额最大，再按员工号最小。pay.csv 与工作簿可编辑 hours 填七月实际计薪工时，不填季度累计数或折合份额。财务改动七月工时时，跨越 40 小时档线的部分应当自动换档。
""")
        _mail(work, "HR-Q3-ROUTE", "2025-07-01", "hr", "七月结算｜追溯调班联签与结转",
              "工时中心结账后会补齐追溯调班登记和联签流水。每张厂票按 site,ticket,revision 对两份资料；"
              "同一版本须有财务和人事各一枚在 8 月 3 日 18:00（含）前的签发记录，重复记录不重计，草拟无效。"
              "仅从已双签版本选最高整版，再看结果，撤回即无指令。单签、迟签高版不覆盖有效低版。"
              "例如北厂 Q17 第一版双签改派 25%，第二版撤回仅人事签发，则沿用第一版。"
              "仅对七月有效工时票调班，按原工作日期和有效人事条款确定原项目，工时仍属原员工。"
              "在原票折算为计薪工时后，按指令百分比划给 destination，余数留原归属。"
              "原待查票若部分改派，只要仍余正待查量就列待查表；被全部划清则销待查。"
              "最后才筛本期放行项目。另做 out/time_transfers.csv，列出全部生效改派指令，"
              "含工时已撤或非本月而尚未执行的指令，表头 site,ticket,revision,destination,percent，比例 25% 填 25。")
    elif turn == 7:
        proposals, stamps = generate_orders(seed)
        _csv(work / PROPOSALS, ",".join((*ORDER_FIELDS, "decision")), proposals)
        _csv(work / STAMPS, "site,ticket,revision,authority,decision,signed", stamps)
        prompt += " 本批季度结转与追溯调班按先前签发的合同、联签要求办理，附生效指令表 out/time_transfers.csv。"
    return prompt


def resolve_orders(proposals, stamps):
    signed = defaultdict(set)
    for stamp in stamps:
        if stamp["decision"] == "签发" and stamp["signed"] <= CUTOFF:
            key = stamp["site"], stamp["ticket"], stamp["revision"]
            signed[key].add(stamp["authority"])
    resolved = {}
    for row in proposals:
        key = row["site"], row["ticket"]
        if not {"财务", "人事"} <= signed[*key, row["revision"]]:
            continue
        if key not in resolved or int(row["revision"]) > int(resolved[key]["revision"]):
            resolved[key] = row
    return {k:r for k,r in resolved.items() if r["decision"] == "改派"}


def facts(work, index, history=False):
    orders = resolve_orders(read_csv(work / PROPOSALS), read_csv(work / STAMPS))
    rows = migration.decoded(work, index)
    pools, hours, caps, pending = payroll.reconstruct(work, 2, history=history, rows=rows, orders=orders)
    register = payroll.latest(read_csv(work / CARRY), ("project", "employee"), "signed",
                              "2025-06-30 18:00", {"签发"}, history)
    carry = {(r["project"], r["employee"]): Decimal(r["prior_hours"]) for r in register}
    awards = payroll.awards(hours, pools, caps, carry)
    return dict(pools=pools, hours=hours, caps=caps, pending=pending, index=index, orders=orders,
                carry=carry, pay=payroll.pay_rows(hours, awards))


def reference(run, turn, variant, level, seed):
    if turn != 7:
        migration.reference(run, turn, variant, 3, seed)
        return
    work = run / "work"
    out = work / "out"
    data = facts(work, read_csv(out / migration.INDEX), history=True)
    write_csv(out / "time_transfers.csv", ORDER_FIELDS, [{k:r[k] for k in ORDER_FIELDS} for r in data["orders"].values()])
    write_csv(out / "time_review.csv", ("site", "ticket"), [dict(site=s,ticket=t) for s,t in sorted(data["pending"])])
    write_csv(out / "pay.csv", PAY, data["pay"])
    payroll.workbook(out / "bonus.xlsx", data["pools"], data["hours"], data["caps"], data["carry"])


def pristine(variant, seed):
    with TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "inbox").mkdir()
        for turn in range(1,8):
            release(work,turn,variant,4,seed)
            if turn == 3:
                index = migration.compile_index(work)
        return facts(work,index)


def expected_pay(variant, level, seed):
    return pristine(variant,seed)["pay"]


def dispatch_check(run, official):
    actual, submitted = payroll.keyed_rows(Table(run / "snapshots/7/time_transfers.csv"), ("site", "ticket"))
    eligible = actual.keys() & official.keys()
    correct = sum(actual[k].get("destination") == official[k]["destination"] and
                  payroll.numeric(actual[k],"percent") == Decimal(official[k]["percent"]) and
                  payroll.numeric(actual[k],"revision") == Decimal(official[k]["revision"]) for k in eligible)
    denominator = len(submitted | official.keys())
    return round(3*correct/denominator,4), 3, f"R7 jointly signed effective instructions {correct}/{denominator}"


def checks(run, variant, level, seed):
    oracle = pristine(variant,seed)
    weights = {"pay.archive_coverage":1, "pay.archive_employee":1, "pay.archive_contract":2, "pay.archive_retained":1,
               "pay.release_scope":1, "pay.released_pool":2, "pay.roster":1, "pay.pending_tickets":2,
               "pay.transfer_hours":3, "pay.other_hours":4, "pay.individual_allocation":5, "pay.conserved_pools":1,
               "pay.workbook_baseline":2, "pay.workbook_edited_hours":3, "pay.workbook_edited_pools":3}
    components = migration.archive_checks(run,oracle["index"])
    components.update(payroll.grade(run,variant,2,seed,oracle=oracle))
    result = {"pay.joint_dispatch": dispatch_check(run,oracle["orders"])}
    for code, (earned, maximum, reason) in components.items():
        weight = weights[code]
        result[code] = round(weight*earned/maximum,4), weight, reason
    return result
