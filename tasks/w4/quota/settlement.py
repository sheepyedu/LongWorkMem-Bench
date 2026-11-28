"""Public historical transfer agreements for edition 4.2."""

from ..annex import csvfile

# Reference, receiving case, source case, relationship, guaranteed seats, maximum.
AGREEMENTS = (
    ("T37", "J01", "J07", "接续", 7, 4),
    ("T19", "J04", "J07", "独立", 7, 4),
    ("T52", "J03", "J11", "独立", 6, 3),
    ("T08", "J07", "J11", "接续", 6, 3),
    ("T41", "J06", "J01", "接续", 6, 4),
    ("T26", "J09", "J01", "独立", 6, 4),
    ("T63", "J08", "J10", "独立", 6, 3),
    ("T14", "J12", "J10", "接续", 6, 3),
)
# reference, issued, effective, through; a distinct cut can change the answer.
RELEASES = tuple((ref, 7, 9, 12) for ref, *_ in AGREEMENTS)
STOPS = (("T37", 10, 11), ("T08", 10, 10), ("T26", 11, 12), ("T63", 11, 11))
GUIDE = """
本期另有历史保障合同。第2日的合同对照表仅借阅当班，须保留单号、受益案、来源案和承诺性质。第7日后按单号收到生效的划转及停兑通知。按计划日和当时已收到的材料判断，有效区间含首尾，停兑自指定生效日起持续。某日交班或内审不得以晚到通知追改原结论。
每份有效历史合同的保障额为 min(上限,max(0,保证数−来源案第3日柜面结班实占))。性质“接续”表示与原续办券履行同一承诺，兑入取两者较大值；“独立”表示两个独立义务，兑入为两者之和。没有有效历史合同则只计仍有效的原券。原券注销与历史合同停兑互不代替。将合并后的数作为排期预兑、调度兑入及预约预测的输入；仍按正数兑入优先号减一办理。新增资料不要求另交文稿。
站务档案中另有上一班的预约工作簿，原公式可能沿用已停用的分配办法。第8、12日交班前，请核实部分容量时同站按顺位分配、不能满足全额也要先安排可办数量，其他站不受影响。可修复原件或在空模板中重建。
"""


def release(work, day):
    folder = work / "inbox" / f"06-{day:02}"
    if day == 2:
        csvfile(
            folder / "历史保障签章表.csv",
            "单号,受益案,来源案,性质,保证数,上限",
            AGREEMENTS,
        )
    if day == 3:
        (work / "inbox/06-02/历史保障签章表.csv").unlink()
    if day == 7:
        csvfile(folder / "划转单.csv", "单号,签发日,生效日,末日", RELEASES)
    if day in (10, 11):
        csvfile(
            folder / "停兑单.csv",
            "单号,签发日,生效日",
            [s for s in STOPS if s[1] == day],
        )


def entitlement(case, day, known, history, legacy):
    for ref, receiver, source, kind, guarantee, limit in AGREEMENTS:
        if receiver != case:
            continue
        active = any(
            r == ref and issued <= known and start <= day <= end
            for r, issued, start, end in RELEASES
        )
        stopped = any(
            r == ref and issued <= known and start <= day for r, issued, start in STOPS
        )
        if active and not stopped:
            amount = min(limit, max(0, guarantee - history[source]["实占"]))
            return max(legacy, amount) if kind == "接续" else legacy + amount
    return legacy
