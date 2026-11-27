"""Migration of the July payroll time clocks and their signed archival index."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import random
from tempfile import TemporaryDirectory

from . import advanced_pay as prior
from . import advanced_pay_checks as payroll
from .reference import PAY, read_csv, write_csv
from .scoring_tables import Table
from .world import _csv, _mail


REGISTER = Path("input/人事移交/胸牌迁移签署登记.csv")
CONTRACTS = Path("input/人事移交/计时合同签署登记.csv")
DRAFT = Path("input/人事移交/联测用导入预案.csv")
INDEX = Path("frozen/payroll-index.csv")
FIELDS = ("site", "badge", "valid_from", "valid_to", "employee", "contract", "rate")
PERIODS = (("2025-06-01","2025-07-15"), ("2025-07-16","2025-08-03"))
RATES = {"钟A": (1,1), "钟B": (3,4), "钟C": (5,4), "钟D": (3,2)}
CUTOFF = "2025-06-30 18:00"


def assignment(seed):
    generator = random.Random(seed + 451)
    plan = []
    for site in ("东厂", "西厂"):
        people = prior.staff(2)
        generator.shuffle(people)
        shift = generator.randrange(1, len(people))
        for ix, (start, end) in enumerate(PERIODS):
            for slot in range(len(people)):
                p = people[(slot + ix * shift) % len(people)]
                contract = generator.choice(list(RATES))
                plan.append(dict(site=site, badge=f"C{slot + 101}", valid_from=start, valid_to=end,
                                 employee=p, contract=contract))
    return plan


def issue_register(work, seed):
    rows = []
    for i, record in enumerate(assignment(seed)):
        base = [record[k] for k in FIELDS[:-1]]
        key = f"迁-{1000+i}"
        if i % 3 == 0:
            old = base.copy()
            old[-2] = "E24" if base[-2] != "E24" else "E04"
            rows.append([key,1,*old,"签发","2025-06-23 10:00"])
        rows.append([key,2,*base,"签发","2025-06-30 18:00"])
        if i % 7 == 0:
            tentative = base.copy()
            tentative[-1] = "钟B" if base[-1] != "钟B" else "钟D"
            rows.extend([[key,3,*tentative,"草拟","2025-06-30 17:30"],
                         [key,4,*tentative,"签发","2025-06-30 18:05"]])
        if i % 11 == 0:
            rows.extend([[f"访-{i}",1,*base,"签发","2025-06-25 14:00"],
                         [f"访-{i}",2,*base,"撤销","2025-06-30 15:00"]])
    generator = random.Random(seed + 426)
    generator.shuffle(rows)
    cols = "document,revision," + ",".join(FIELDS[:-1]) + ",decision,signed"
    _csv(work / REGISTER, cols, rows)
    contract_rows = []
    for key, (num, den) in RATES.items():
        contract_rows.extend([
            (key,1,1,1,"签发","2025-06-18 08:00"), (key,2,num,den,"签发","2025-06-30 17:55"),
            (key,3,2,1,"草拟","2025-06-30 17:58"), (key,4,2,1,"签发","2025-06-30 18:01")])
    generator.shuffle(contract_rows)
    _csv(work / CONTRACTS, "contract,revision,pay_minutes,clock_minutes,decision,signed", contract_rows)
    _csv(work / DRAFT, "site,badge,employee,contract,status",
         [(r["site"],r["badge"],r["employee"],"钟A","联测") for r in assignment(seed)[:24]])


def compile_index(work):
    stamps = {"签发", "撤销"}
    cards = payroll.latest(read_csv(work / REGISTER), ["document"], "signed", CUTOFF, stamps, False)
    rates = payroll.latest(read_csv(work / CONTRACTS), ["contract"], "signed", CUTOFF, stamps, False)
    ratios = {r["contract"]: Decimal(r["pay_minutes"])/Decimal(r["clock_minutes"])
              for r in rates if r["decision"] == "签发"}
    return [{**{k:r[k] for k in FIELDS[:-1]}, "rate":ratios[r["contract"]]}
            for r in cards if r["decision"] == "签发"]


def encode_time_exports(work, seed):
    mappings = {(r["site"], r["employee"], r["valid_from"]): r for r in assignment(seed)}
    directory = work / "input/工时中心"
    for name in ("主账.csv", "补正.csv"):
        rows = read_csv(directory / name)
        for row in rows:
            period = PERIODS[0] if row["worked"] <= PERIODS[0][1] else PERIODS[1]
            info = mappings[row["site"],row.pop("employee"),period[0]]
            row["badge"] = info["badge"]
            num, den = RATES[info["contract"]]
            minutes = Decimal(row["units"]) * (60 if row["unit"] == "H" else 1) * den / num
            if row["unit"] == "H" and minutes % 3 == 0:
                row["units"] = minutes / 60
            else:
                row.update(unit="MIN", units=minutes)
        write_csv(directory / name, prior.TIME_FIELDS.replace("employee", "badge").split(","), rows)


def release(work, turn, variant, level, seed):
    prompt = prior.release(work, turn, variant, 2, seed)
    if turn == 1:
        _mail(work, "IT-MIG-06", "2025-06-26", "it", "计时终端换代｜随六月结账移交",
              "本次迁移由财务代管对照索引。人事签署册随后到件，与六月底账同一批归档。"
              "结账后原登记和联测稿从共享盘撤下，后续应使用已报归档。"
              "请交 out/frozen/payroll-index.csv，表头 site,badge,valid_from,valid_to,employee,contract,rate。"
              "每一条有效厂区、胸牌、起止日期组合列一行，日期 ISO，含两端；倍率 rate 填小数，125% 填 1.25。")
    elif turn == 2:
        issue_register(work, seed)
        _mail(work, "HR-MIG-0630", "2025-06-30", "hr", "计时技术移交｜签署两册",
              "胸牌以厂为单位编号，交接后可能再分配；按实际工作日查有效区间。迁移与合同均以六月三十日18:00（含）为签署截点，"
              "各自以 document、contract 为整版主键，已签发或撤销中取最高 revision，撤销后整份作废。联测导入和草拟未签不采用。"
              "pay_minutes/clock_minutes 是实录时长折算为计薪时长的倍率。同一合同在两厂可共用。"
              "按 IT-MIG-06 随关账归档，后续原册下线。")
    elif turn == 4:
        for file in (REGISTER, CONTRACTS, DRAFT):
            (work / file).unlink(missing_ok=True)
    elif turn == 7:
        encode_time_exports(work, seed)
        prompt += " 两厂交来的均为终端实录，沿用关账时移交的技术口径换算为计薪工时。"
    return prompt


def decoded(work, index):
    by_badge = defaultdict(list)
    for r in index:
        by_badge[r["site"],r["badge"]].append(r)
    rows = read_csv(work / "input/工时中心/主账.csv") + read_csv(work / "input/工时中心/补正.csv")
    for row in rows:
        matches = [r for r in by_badge[row["site"],row["badge"]] if r["valid_from"] <= row["worked"] <= r["valid_to"]]
        if len(matches) != 1:
            raise ValueError(f"Missing or overlapping historical badge assignment for {row['site']}/{row['badge']}")
        r, = matches
        row["employee"] = r["employee"]
        row["units"] = Decimal(row["units"]) * Decimal(r["rate"])
    return rows


def reference(run, turn, variant, level, seed):
    work, out = run / "work", run / "work/out"
    if turn == 3:
        write_csv(out / INDEX, FIELDS, compile_index(work))
    elif turn == 6:
        payroll.solve(work, turn, 2)
    elif turn == 7:
        rows = decoded(work, read_csv(out / INDEX))
        pools, hours, caps, pending = payroll.reconstruct(work,2,history=True,rows=rows)
        write_csv(out / "time_review.csv", ("site", "ticket"), [dict(site=s,ticket=t) for s,t in sorted(pending)])
        write_csv(out / "pay.csv", PAY, payroll.pay_rows(hours,payroll.awards(hours,pools,caps)))
        payroll.workbook(out / "bonus.xlsx",pools,hours,caps)


def pristine(variant, seed):
    with TemporaryDirectory() as temp:
        work = Path(temp)
        (work / "inbox").mkdir()
        for turn in range(1, 8):
            release(work,turn,variant,3,seed)
            if turn == 3:
                index = compile_index(work)
        pools, hours, caps, pending = payroll.reconstruct(work,2,rows=decoded(work,index))
        return dict(pools=pools,hours=hours,caps=caps,pending=pending,index=index,
                    pay=payroll.pay_rows(hours,payroll.awards(hours,pools,caps)))


def expected_pay(variant, level, seed):
    return pristine(variant, seed)["pay"]


def archive_checks(run, official):
    source = run / "snapshots/3" / INDEX
    actual = Table(source)
    keys = FIELDS[:4]
    expected = {tuple(r[k] for k in keys):r for r in official}
    rows, submitted = payroll.keyed_rows(actual, keys)
    denominator = len(expected.keys() | submitted)
    good = expected.keys() & rows.keys()
    count_employee = sum(expected[k]["employee"] == rows[k].get("employee") for k in good)
    count_terms = sum(expected[k]["contract"] == rows[k].get("contract") and
                      expected[k]["rate"] == payroll.numeric(rows[k],"rate") for k in good)

    def semantic(table):
        indexed, all_keys = payroll.keyed_rows(table, keys)
        if all_keys != expected.keys() or all_keys != indexed.keys() or not set(FIELDS) <= set(table.headers):
            return None
        terms = {}
        for key, row in indexed.items():
            rate = payroll.numeric(row,"rate")
            if rate is None or rate <= 0 or not row["employee"] or not row["contract"]:
                return None
            terms[key] = row["employee"], row["contract"], rate
        return terms
    filed = semantic(actual)
    stable = filed is not None and all(semantic(Table(run / "snapshots" / str(t) / INDEX)) == filed for t in range(4,10))
    return {
        "pay.archive_coverage": (round(2*len(good)/denominator,4),2,f"R3 unique plant/badge/validity windows {len(good)}/{denominator}"),
        "pay.archive_employee": (round(2*count_employee/denominator,4),2,f"R3 historical employee {count_employee}/{denominator}"),
        "pay.archive_contract": (round(3*count_terms/denominator,4),3,f"R3 signed contract and ratio {count_terms}/{denominator}"),
        "pay.archive_retained": (int(stable),1,"R4–R9 index compared field-by-field to R3 delivery"),
    }


def checks(run,variant,level,seed):
    oracle = pristine(variant,seed)
    result = archive_checks(run,oracle["index"])
    weights = {"pay.release_scope":1,"pay.released_pool":3,
               "pay.roster":2,"pay.pending_tickets":2,
               "pay.transfer_hours":3,"pay.other_hours":3,
               "pay.individual_allocation":4,"pay.conserved_pools":1,
               "pay.workbook_baseline":2,"pay.workbook_edited_hours":3,"pay.workbook_edited_pools":3}
    for code,(earned,max_points,reason) in payroll.grade(run,variant,2,seed,oracle=oracle).items():
        weight = weights[code]
        result[code] = round(weight * earned / max_points, 4), weight, reason
    return result
