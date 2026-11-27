"""Public C1 follow-on: staged cross-desk settlement data and release contracts."""

import csv
import json
from pathlib import Path
import random

NAMES = ("intake", "routing", "cutover", "incident", "corrections", "close")
RUN = "python3 project/settle.py INPUT_DIR PLAN_JSON OUTPUT_JSON"
FORMAT = """服务台对账交换契约
调用 python3 project/settle.py INPUT_DIR PLAN_JSON OUTPUT_JSON。读取该目录下所有 packets/*.jsonl 与已发布的制度文件。
PLAN_JSON 为 {"day":业务截止日整数,"lanes":{"e":入站水位,"w":水位,"n":水位}}，均含端点。
先按所属 lane 的 seq 和业务日 day 双重筛选，再按 eid 去重。完全相同的补送只计一次。事件均在同一 tenant 内结算；工单号逐字符保留，包括前导零。没有生效的显式换绑登记时，003 和 0003 是两张独立工单。
每行包含 eid,tenant,ticket,lane,seq,day,order,kind,units,dept。order 是全局稳定入站编号。依(day,order)从小到大记账。
credit 增加工时，use 扣减正整数工时。余额不足整笔拒绝；不允许先欠后补。成功与否都要入稽核。
业务输出为 JSON 对象：accounts 数组每行 [tenant,规范工单号,余额]（成功过的账户，即使余额为零也保留）；
audit 数组每行 [唯一eid,处置]，处置为 posted、denied，以及后续协议规定的处置。totals 数组每行 [tenant,余额之和]。
各数组顺序不限。不写未可见事件，不交混合多个方案的总表。每次来件都需按本轮 PLAN 运行并交 out/<方案名>.json；
交付程序可在新目录、不同方案和新来件上重跑。旧交付保留原样。
"""
ROUTE = """别名登记册 aliases.csv 按 tenant、raw 和业务日 [start,end] 查找 canon。未匹配保留原号。
同一原号可以阶段换绑，不递归解析。只按该事件自己的 day 归并，不能拿交付日去映射。"""
TRANSFER = """跨台调拨的 kind 为 leg。按 (tenant,ref) 收齐一正一负两张不同eid，绝对工时相等且规范化后是不同账户；只到一张为 pending，成员超过两张或不合约为 invalid。
仅用本方案可见的来件判断完整性。两个成员各按自身 day 解析别名；整组在最大 day、最大 order 的位置原子入账。扣出方余额不足则两个成员均 denied；成功均 posted。失败不得创建零余额收款账户。
"""
RECALL = """kind=recall 是稽核组的撤令，ref 指向本 tenant 的调拨组。先从本方案可见的完整有效调拨中查找目标；
只有签发人等于早期交接通知的当班签发人、且撤令 order 大于组内最大 order、day 不早于组的生效日才有权撤回。符合条件的多张撤令按(day,order)首张 posted，其余 duplicate；其他撤令 denied。
被撤回的两腿均记 void，按从未发生该调拨重新计算后续扣减，即使原调拨当初余额不足也适用。撤令本身不产生账户。"""
INCIDENT = """排障交接：input/incident.jsonl 来自独立调度系统。按 (站点,作业) 取最大的 attempt，同次按最大 stamp。
只导出最新状态仍为 failed 的 [站点,作业,attempt] 三元组，写 out/incident.json（JSON数组）。"""
FINAL = """归档交割：input/jobs/close.json 为主结算；另对 input/jobs/archive-*.json 每个方案各出同名结果到 out/。
同时从最终源码对原先 intake、routing、cutover 的封存交件保持原交付文件不动。新发布的迟到件在旧水位以外。
"""

FUNDING = """财务数据字典：每个credit的cents是该整笔凭证的总分币，工时单位不可拆。凭证的第i个单位（从0开始）的成本为 floor((i+1)*cents/units)-floor(i*cents/units)。
所有处置遵循先进先出。挑选顺序取原credit的(day,order)，再取原凭证单位序号升序；调拨后保留原始序号与成本。一个账户可能收到同一凭证的多个不连续片段。
每次交割的 JSON 另存 lots：每行[tenant,当前工单号,原credit的eid,剩余单位,剩余分币]；usage：每行[已准use的eid,原credit的eid,耗用单位,耗用分币]。相同键合为一行，零单位不出行。"""
TRANSFER_COST = """从本轮起所有新交件（含历史截止日的归档方案）均须含 travel；没有调拨时交 "travel": []。每行[已入账的负腿eid,原credit的eid,调拨单位,调拨分币]，按前期财务数据字典取用；业务撤回时重演产生新的分摊，不能留下已撤回的调拨分摊。"""


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf8")


def generate(seed, level, variant):
    rng = random.Random(seed)
    size = 64 if level == 1 else 192
    tenants = ["ops", "field", "lab"]
    aliases = []
    batches = {n: [] for n in NAMES}
    lanes = {k: 0 for k in ("e", "w", "n")}
    cuts = {}
    seq = 0
    approvers = rng.sample(
        ["north-chair", "late-shift", "dispatch-4", "audit-2", "duty-9", "panel-6"], 2
    )

    def add(batch, tenant, ticket, day, kind, units, lane=None, **extra):
        nonlocal seq
        seq += 1
        lane = lane or rng.choice(list(lanes))
        lanes[lane] += 1
        row = dict(
            eid=f"E{seed:x}-{seq:05}",
            tenant=tenant,
            ticket=ticket,
            lane=lane,
            seq=lanes[lane],
            day=day,
            order=seq,
            kind=kind,
            units=units,
            dept=tenant,
            **extra,
        )
        if level >= 2 and kind == "credit":
            row["cents"] = rng.randint(1, units * 14)
        batches[batch].append(row)
        return row

    for i in range(size):
        t = tenants[i % 3]
        a = f"{i:04}"
        b = f"{i:03}"
        for acct in (a, b):
            add("intake", t, acct, 1, "credit", rng.randint(5, 18))
            add("intake", t, acct, 4, "use", rng.randint(4, 20))
        aliases.extend([(t, "D" + a, 2, 5, a), (t, "D" + a, 6, 12, b)])
    cuts["intake"] = dict(lanes)
    for i in range(size):
        add(
            "routing",
            tenants[i % 3],
            "D" + f"{i:04}",
            rng.choice((2, 5, 6, 8)),
            "credit",
            rng.randint(1, 7),
        )
    cuts["routing"] = dict(lanes)
    for i in range(size):
        ref = f"T{i // 3:03}"
        t = tenants[i % 3]
        a = f"{i:04}"
        b = f"{i:03}"
        qty = rng.randint(4, 16)
        order_day = rng.choice((3, 5, 7))
        add("cutover", t, a, order_day, "leg", -qty, "w", ref=ref)
        if i % 7 != 0:
            add(
                "cutover",
                t,
                b,
                order_day + 1,
                "leg",
                qty if i % 13 else qty + 1,
                "e",
                ref=ref,
            )
        if level >= 2 and i % 19 == 0:
            add("cutover", t, "D" + a, 8, "leg", qty, "n", ref=ref)
        add("cutover", t, b, 9, "use", rng.randint(8, 16))
    cuts["cutover"] = dict(lanes)
    cuts["incident"] = dict(lanes)
    for i in range(size):
        t = tenants[i % 3]
        ref = f"T{i // 3:03}"
        b = f"{i:03}"
        if i % 7 == 0:
            orig = next(
                r
                for r in batches["cutover"]
                if r.get("ref") == ref and r["tenant"] == t and r["units"] < 0
            )
            add("corrections", t, b, 6, "leg", -orig["units"], "e", ref=ref)
        for j in range(2 if level >= 2 and i % 3 == 0 else 1):
            add(
                "corrections",
                t,
                b,
                8 + j,
                "recall",
                0,
                "n",
                ref=ref,
                signer=approvers[(i + j) % 2],
            )
        if i % 4 == 0:
            add("corrections", t, f"{i:04}", 2, "credit", 4)
    cuts["corrections"] = dict(lanes)
    for i in range(size):
        add(
            "close",
            tenants[i % 3],
            "D" + f"{i:04}",
            rng.randint(3, 10),
            "use",
            rng.randint(4, 17),
        )
    cuts["close"] = dict(lanes)
    for rows in batches.values():
        rows.extend(rows[::11])
        rng.shuffle(rows)
    return batches, cuts, aliases, approvers


def release_ledger(work, turn, variant, seed, level):
    work = Path(work)
    inp = work / "input"
    jobs = inp / "jobs"
    pk = inp / "packets"
    for p in (jobs, pk):
        p.mkdir(parents=True, exist_ok=True)
    name = NAMES[turn - 1]
    batches, cuts, aliases, approvers = generate(seed, level, variant)
    if turn == 1:
        (inp / "interface.txt").write_text(FORMAT)
        if level >= 2:
            (inp / "finance.txt").write_text(FUNDING)
    if turn == 2:
        with (inp / "aliases.csv").open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["tenant", "raw", "start", "end", "canon"])
            writer.writerows(aliases)
        (inp / "routing.txt").write_text(ROUTE)
        (inp / "handover.txt").write_text(
            "今期跨台调拨的撤令由 "
            + approvers[0 if variant == "A" else 1]
            + " 单独签发；后续各次交割沿用。"
        )
    if turn == 3:
        (inp / "transfer.txt").write_text(
            TRANSFER + (TRANSFER_COST if level >= 2 else "")
        )
    if turn == 4:
        rng = random.Random(seed + 80)
        rows = [
            dict(
                site=f"S{i % 4}",
                job=f"J{i % 31}",
                attempt=(i // 124) % 4,
                stamp=i,
                result=rng.choice(["failed", "done", "retry"]),
            )
            for i in range(640 if level == 1 else 2048)
        ]
        rng.shuffle(rows)
        (inp / "incident.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows)
        )
        return INCIDENT
    if turn == 5:
        (inp / "appeal.txt").write_text(RECALL)
    rows = batches[name]
    for k in range(3 if level == 1 else 9):
        chunk = rows[k :: 3 if level == 1 else 9]
        (pk / f"{name}-{k:02}.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in chunk)
        )
    plan = dict(day=12, lanes=cuts[name])
    write_json(jobs / (name + ".json"), plan)
    if turn == 6:
        for j in range(3 if level == 1 else 9):
            lanes = {
                k: cuts[NAMES[(j + i) % 5]][k] for i, k in enumerate(plan["lanes"])
            }
            write_json(jobs / f"archive-{j}.json", dict(day=4 + j % 6, lanes=lanes))
    text = [
        "请接手工单工时对账，按 interface.txt 实现可复跑入口并结算首批。",
        "换绑表与当班交接已到，请按新登记结算。",
        "跨台调拨已上线，核对各站发来的两联单。",
        "",
        "回到工单。迟到的补正、撤令和处理约定已到，请按已签口径完成本批。",
        FINAL,
    ][turn - 1]
    if level >= 2 and turn == 1:
        text += " 同时纳入财务数据字典 finance.txt 的单位成本归集。"
    return text + f" 本轮方案 input/jobs/{name}.json，交 out/{name}.json。入口 {RUN}。"


def release(work, turn, variant, seed, level):
    if level != 3:
        return release_ledger(work, turn, variant, seed, level)
    from . import reserve
    prompt = release_ledger(work, turn, variant, seed, 2) if turn <= 6 else ""
    approvers = generate(seed, 2, variant)[3]
    return prompt + reserve.issue(Path(work), turn, seed, approvers)
