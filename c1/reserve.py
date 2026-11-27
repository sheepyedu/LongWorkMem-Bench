"""Transient signed desk instructions and the reopened guarantee ledger (level 3)."""
import csv
import json
import random

DESKS = ("ops", "field", "lab")
BANDS = ("red", "blue", "green", "gold")
STAGES = (1, 3, 4)
CUTS = (3, 6, 9)
NOTICE = "guarantee-window.csv"
FORMAT = """保证金台账是独立账簿。早先三张窗口通知须按原版本使用。每个 (desk,band) 按申请日 day 取 start<=day 且 start 最大的通知；end 含端点。
新通知一经生效就永久替换旧通知，即使新通知后来到期也不恢复旧条款。缺通知或已到期为 expired，错误渠道为 channel，非当班签发人为 signature，按此优先顺序。
各截止日独立从空账重演：day<=cut 的请求按(day,seq)排序，重复 id 只办一次。上述资格通过后，若本组累计已占保证金加申请金额超过该日有效额度 limit，则整笔记 capacity，否则 posted。
换通知时累计已占金额保留，额度降低不追扣。只有 posted 记账；所有可见行均入处置。签发人是第二轮交接授权，本批未重发通知。
调用 python3 project/reserve.py INPUT_DIR OUTPUT_JSON，读取 INPUT_DIR/guarantees.jsonl；不得假定文件名以外的目录位置或固定申请编号。
输出对象含 decisions 每行 [cut,id,处置]，posted 每行 [cut,desk,band,id,金额]，balance 每行 [cut,desk,band,累计已占]（只列成功过的组）。三个截止日为3、6、9。数组顺序不限。交 out/guarantee.json。"""


def notices(seed):
    rng = random.Random(seed + 550131)
    table = {}
    for stage in STAGES:
        entries = []
        for i, desk in enumerate(DESKS):
            for j, band in enumerate(BANDS):
                if stage == 3 and (i+j)%3 == 0 or stage == 4 and (i+j)%2 == 0:
                    continue
                start = {1:1,3:4,4:7}[stage]
                entries.append(dict(desk=desk,band=band,start=start,end=rng.choice((start+1,9,10)),
                                    channel=rng.choice(("dock","mail","counter")),limit=rng.randrange(22,62)))
        table[stage] = entries
    return table


def requests(seed, authority, other, batch):
    rng = random.Random(seed * 103 + batch + 538)
    rows = []
    for seq in range(1, 721):
        rows.append(dict(id=f"G{batch}-{seq:04}",seq=seq,day=rng.randint(1,9),desk=rng.choice(DESKS),
                         band=rng.choice(BANDS),channel=rng.choice(("dock","mail","counter")),
                         signer=rng.choice((authority,other)),amount=rng.randrange(1,22)))
    rows.extend(rows[::17])
    rng.shuffle(rows)
    return rows


def issue(work, turn, seed, approvers):
    inp = work/'input'
    notice = inp/NOTICE
    notice.unlink(missing_ok=True)
    if turn in STAGES:
        rows=notices(seed)[turn]
        with notice.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return " 保证金台本轮另送一张分组授权通知 input/guarantee-window.csv，仅本轮可阅；请保留每版及其生效、截止、渠道、额度，日后可能需处理历史来件。"
    if turn == 7:
        (inp/'guarantee-contract.txt').write_text(FORMAT)
        (inp/'guarantees.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in requests(seed,*approvers,batch=0)))
        return "保证金台重新开账。请用前期逐轮交接的各版通知和当班签发人，按 input/guarantee-contract.txt 结清三个历史截止日并交付可复跑入口。"
    return ""
