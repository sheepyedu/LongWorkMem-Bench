"""Dated reserve mandates across four postings in the ongoing close."""
from collections import defaultdict
from decimal import Decimal
import random
import re
import unicodedata

from .scoring_tables import InvalidArtifact, Table, number
from .world import _csv, _text

DATES = {3:"2025-06-30", 5:"2025-07-08", 8:"2025-08-04", 9:"2025-08-05"}
FIELDS = "office,case,project,desk,authority,decision,target,change"
INPUTS = "office,case,kind,employee,project,worked,vendor,amount"
KINDS = ("退汇", "贷差", "待清")


def mandate(seed):
    rng = random.Random(f"reserve mandates/{seed}")
    ids = rng.sample(range(1000, 9999), 10)
    base = {}
    for i, (project, kind) in enumerate((p, k) for p in "甲乙" for k in KINDS):
        base[project, kind] = (f"岗{ids[i]}", rng.randrange(20, 50)*10)
    return dict(base=base, base_id=f"常{ids[6]}", kind=rng.choice(KINDS), delegate=f"岗{ids[7]}",
                temp_cap=rng.randrange(8,16)*10, temporary=f"代{ids[8]}", stop=f"停{ids[9]}",
                vendor=rng.choice(("舟泰","荃安","栩新")))


def cases(turn, seed):
    # Two offices intentionally reuse case numbers. Revised Aug 5 items retain their identity.
    day = DATES[turn]
    r = mandate(seed)
    rng = random.Random(f"reserve cases/{seed}/{min(turn,8)}")
    items = []
    for office in ("江东","南港"):
        for i in range(18):
            kind = r["kind"] if i < 8 else KINDS[i % 3]
            project = "共享" if i % 4 in (0,1) else ("甲","乙")[i % 2]
            employee = "E07" if project == "共享" else f"E{i%14+1:02}"
            worked = day if turn in (3,5) else ("2025-07-15" if i % 4 == 0 else "2025-07-16")
            vendor = r["vendor"] if i in (5,11,16) else "恒力"
            amount = rng.choice([r["temp_cap"], r["temp_cap"]+1,
                                 r["base"]["乙",kind][1], r["base"]["甲",kind][1]+1, 75])
            if turn == 9 and i % 6 == 2:
                amount += 40
            items.append(dict(office=office,case=f"K{i+1:02}",kind=kind,employee=employee,
                              project=project,worked=worked,vendor=vendor,amount=amount))
    return items


def form(turn):
    return "reserve/" + DATES[turn] + ".csv"


def release(work, turn, seed):
    r = mandate(seed)
    if turn == 1:
        _text(work/"input/资金运营/争议预留办理规程.txt", """
争议款预留通过 out/reserve/YYYY-MM-DD.csv 办理（日期取本次办理日）。保存即按该轮申报入账，旧日期原表留存。字段 office,case,project,desk,authority,decision,target,change。每个(office,case)独立一行。
project 取专属项目；共享记录均由 E07 经办，按个人工作日 worked 的常设归口，从甲转乙的日期见 HR-0628。预留归口只依据该常设批复。办理日决定当时仍有效的额度及经办岗。各口头授权在该轮委托内正式生效，可以自行留底。
金额为正数元。未超过本岗单项上限（含等额）记 BOOK，target 为全额；超过记 HOLD，target 为零。超限也填当时有权经办的岗和授权号。专项停办指令优先，其岗和授权号依停办指令。六月、七月、八月各次办件相互独立，change 填 target；仅 8月5日是对8月4日实际预留的调整，change = 今日 target 减昨天本库本件唯一已申报的有效非负分币金额，缺件、重复、金额无效按零。允许负数。请勿改写昨日申报来代替追调。
""")
        entries = "；".join(f"{p}/{kind}由{desk}办，上限{cap}元" for (p,kind),(desk,cap) in r["base"].items())
        return f" 争议款预留也归你经办。我批准常设授权{r['base_id']}，以下六项一直有效，后续只按明示范围变更：{entries}。按争议预留规程在每次来单时办理。"
    if turn == 4:
        return (f" 会后交接：签发临时代办{r['temporary']}。7月1日至8月4日含首尾，"
                f"两库的乙项目{r['kind']}统一改由{r['delegate']}办理，上限{r['temp_cap']}元。其余仍按常设授权。")
    if turn == 6:
        return (f" 两项更新：自8月1日起，仅江东库撤回上次临时代办，回原岗及原限额。"
                f"另签{r['stop']}，仅在8月4日对两库供应商{r['vendor']}全部暂停预留，交内控岗 IC-01；次日恢复原有效规则。")
    if turn in DATES:
        rows = cases(turn,seed)
        _csv(work/f"input/资金运营/争议清册/{DATES[turn]}.csv", INPUTS,
             [[row[k] for k in INPUTS.split(",")] for row in rows])
        return f" {DATES[turn]}争议清册已到，请依当日授权办理预留入账。"
    return ""


def decision(row, day, r, effective):
    project = row["project"]
    if project == "共享":
        project = "乙" if row["worked"] >= effective else "甲"
    desk, cap = r["base"][project, row["kind"]]
    authority = r["base_id"]
    temporary = (project == "乙" and row["kind"] == r["kind"] and
                 "2025-07-01" <= day <= "2025-08-04" and not (row["office"] == "江东" and day >= "2025-08-01"))
    if temporary:
        desk, cap, authority = r["delegate"], r["temp_cap"], r["temporary"]
    amount = number(row["amount"])
    book = amount <= cap
    if day == "2025-08-04" and row["vendor"] == r["vendor"]:
        desk, authority, book = "IC-01", r["stop"], False
    return dict(office=row["office"], case=row["case"], project=project, desk=desk, authority=authority,
                decision="BOOK" if book else "HOLD", target=amount if book else Decimal(0))


def index(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("office"), row.get("case")].append(row)
    return groups


def filed_amounts(path):
    amounts = {}
    for key, group in index(Table(path).rows).items():
        if len(group) == 1:
            try:
                n = number(group[0].get("target"))
                if n >= 0 and n % Decimal(".01") == 0:
                    amounts[key] = n
            except InvalidArtifact:
                pass
    return amounts


def posting(rows, turn, r, effective, prior):
    entries = []
    for row in rows:
        value = decision(row, DATES[turn], r, effective)
        value["change"] = value["target"] - prior.get((row["office"],row["case"]), 0)
        entries.append(value)
    return entries


def reference(run, turn, variant, level, seed):
    if turn not in DATES:
        return
    work = run/"work"
    effective = re.search(r"生效日 (\d{4}-\d{2}-\d{2})", (work/"inbox/HR-0628.eml").read_text()).group(1)
    raw = Table(work/f"input/资金运营/争议清册/{DATES[turn]}.csv")
    prior = filed_amounts(work/"out"/form(8)) if turn == 9 else {}
    rows = posting(raw.rows, turn, mandate(seed), effective, prior)
    _csv(work/"out"/form(turn),FIELDS,[[r[k] for k in FIELDS.split(",")] for r in rows])


def normalized(field, value):
    if field in ("target", "change"):
        return number(value)
    if field == "desk":
        value = unicodedata.normalize("NFKC", value).strip()
        if re.fullmatch(r"内控岗\s*:?\s*(?:IC-01|\(IC-01\))", value):
            return "IC-01"
    return value


def equal(row, wanted, fields):
    try:
        return all(normalized(k,row[k]) == normalized(k,wanted[k]) for k in fields)
    except (InvalidArtifact, KeyError):
        return False


def checks(run, variant, level, seed):
    snap = run/"snapshots"
    r = mandate(seed)
    effective = {"A":"2025-07-16","B":"2025-08-16"}[variant]
    scores = {}
    for turn in DATES:
        prior = filed_amounts(snap/"8"/form(8)) if turn == 9 else {}
        rows = posting(cases(turn,seed), turn, r, effective, prior)
        expected = {(row["office"],row["case"]):row for row in rows}
        submitted = Table(snap/str(turn)/form(turn))
        actual = index(submitted.rows)
        denominator = len(expected.keys() | actual.keys())
        terms = {"project":(("project",),1), "desk":(("desk",),1), "authority":(("authority",),1),
                 "disposition":(("decision",),1), "amount":(("target","change") if turn != 9 else ("target",),1)}
        if turn == 9:
            terms["adjustment"] = (("change",),3)
        for name,(fields,maximum) in terms.items():
            passed = [k for k in expected.keys() & actual.keys() if len(actual[k]) == 1 and equal(actual[k][0],expected[k],fields)]
            scores[f"memory.r{turn}.{name}"] = (maximum*len(passed)/denominator, maximum,
                f"R{turn} {name}: {len(passed)}/{denominator}; missed {sorted(set(expected)-set(passed))[:4]}")
    retained = 0
    for earlier in (3,5,8):
        first = Table(snap/str(earlier)/form(earlier))
        later = Table(snap/"9"/form(earlier))
        valid_keys = {(r["office"],r["case"]) for r in cases(earlier,seed)}
        initial = index(first.rows)
        if set(initial) != valid_keys or set(first.headers) != set(FIELDS.split(",")):
            continue
        final = index(later.rows)
        retained += (set(final) == valid_keys and all(len(initial[k]) == len(final[k]) == 1 and
                     equal(final[k][0],initial[k][0],FIELDS.split(",")) for k in valid_keys))
    scores["memory.retention"] = (2*retained/3,2,f"R9 retained {retained}/3 actual prior filings")
    return scores


def contrast(runs, seed):
    """Measurable A/B consequences of the same HR instruction, reported outside the score."""
    rules = mandate(seed)
    fields = ("project","desk","authority","decision","target")
    counts = {group:{"matched_both":0, "cases":0} for group in ("must_change","must_stay")}
    for turn in (8,9):
        submissions = {v:index(Table(path/"snapshots"/str(turn)/form(turn)).rows) for v,path in runs.items()}
        for case in cases(turn,seed):
            key = case["office"], case["case"]
            wants = {v:decision(case,DATES[turn],rules,day) for v,day in
                     (("A","2025-07-16"),("B","2025-08-16"))}
            name = "must_stay" if equal(wants["A"],wants["B"],fields) else "must_change"
            counts[name]["cases"] += 1
            counts[name]["matched_both"] += all(len(submissions[v].get(key,[])) == 1 and
                equal(submissions[v][key][0],wants[v],fields) for v in ("A","B"))
    return counts
