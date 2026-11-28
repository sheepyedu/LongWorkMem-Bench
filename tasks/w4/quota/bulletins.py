"""Joint station bulletins and the issue-date register for edition 4.3."""

from . import world
from ..scenario import put

# Columns follow the three business desks: on-site bookings, shuttle, and induction.
REGISTERS = {
    "东港": ("潮", "岸", "湾"),
    "西湾": ("栈", "闸", "汀"),
    "南站": ("桐", "枫", "榆"),
    "北仓": ("丁", "丙", "乙"),
}
RENAMED = {"东港": ("岸", "湾", "潮"), "南站": ("榆", "桐", "枫")}
# issue day, first effective day, last effective day, operational reason
CHANGES = {
    4: (9, 11, "配合联运换班，先预留跨站客户的到场时段。"),
    5: (10, 12, "客户重新确认到场人数，后续班次按本次签收执行。"),
    6: (9, 10, "委托方核对加开窗口。代办签字仅在本站授权期内有效。"),
    8: (10, 10, "为单日检修安排临时接待，检修结束后恢复适用的原件。"),
    9: (9, 9, "当日有车辆转站，临时调整只在本班生效。"),
    10: (11, 12, "晚到确认函列明下一班起的保留与减配。"),
    11: (11, 11, "异议复核期间暂按当日批复接待。"),
}
GUIDE = """
本期四站合署行文。一份联席纪要同时办理现场预约、接驳预约及入场培训，同一客户可以同时参加三项业务；同一流水下三个分册各自签发，使用独立的席位池。本岗位只负责现场预约。纪要正文中的册名是业务依据，不按条款出现次序判断。第2日借阅分册登记簿；第7日有局部换册通知。新册名按纪要的签发日适用，不追改此前签发且仍有效的条款。第2、7日的纪要和借阅件在下一班归还，允许摘录。
纪要每个议案的标题给案号和批文流水，条款分别列签发人、文件性质、有效期、额度和优先号。第2和第7日的纪要代替原来的签发原件表；其余送达日也可能收到新批文。各站同日全部材料按原规程取舍。部分续签只调整优先号，指定沿用早期流水同一业务的额度。按原流水签发时的分册归属追溯；原件期满仍可作为续签引用的数值依据，新签的状态和期限单独判断。登记簿和换册通知本身不改变任何客户席位。
"""


RENEWAL_NOTE = """
撤文通知只撤销明确列出的流水。续签是独立的新批文，引用旧件仅用于确定历史额度：即使被引旧件随后或当日撤销，续签仍按自身的签署状态和有效期办理。要撤续签，通知须列出续签自己的流水。
"""


def parent_serial(day, index):
    if day == 9:
        return 2000 + 10 * index
    if day == 11:
        return 7002 + 10 * index
    return None


def documents():
    rows = world.documents()
    ceilings = {r[0]: r[7] for r in rows}
    for day, (start, end, _) in CHANGES.items():
        for i, (case, *_) in enumerate(world.CASES):
            site, local = divmod(i, 3)
            # Different lines require final countersignature on different days.
            signed = (local + site + day) % 3 != 0
            signer = "代办" if day == 6 else "本部"
            ceiling = (1, 8, 3, 6, 2, 7)[(local + 2 * site + day) % 6]
            parent = parent_serial(day, i)
            if parent is not None:
                ceiling = ceilings[parent]
            priority = (1, 5, 2, 4)[(local + site + day) % 4]
            rows.append(
                (
                    day * 1000 + 10 * i + 5,
                    day,
                    start,
                    end,
                    case,
                    signer,
                    "正本" if signed else "待批",
                    ceiling,
                    priority,
                )
            )
    return rows


def desk_codes(site, day):
    return RENAMED.get(site, REGISTERS[site]) if day >= 9 else REGISTERS[site]


def register_text(rows, heading):
    return (
        heading
        + "\n"
        + "\n".join(
            f"{site}：现场预约用{onsite}册，接驳预约用{shuttle}册，入场培训用{training}册。"
            for site, (onsite, shuttle, training) in rows.items()
        )
        + "\n"
    )


def release(work, day):
    inbox = work / "inbox"
    if day in (3, 8):
        prior = inbox / f"06-{day - 1:02}"
        for name in retired_names(day - 1):
            (prior / name).unlink()
    folder = inbox / f"06-{day:02}"
    if day == 2:
        put(
            folder,
            "分册登记簿.txt",
            register_text(REGISTERS, "四站借阅登记，六月起使用。"),
        )
    if day == 7:
        put(
            folder,
            "换册交接单.txt",
            register_text(
                RENAMED, "六月9日起签发的新纪要依下列对应办理；未列站仍用原册。"
            ),
        )
    records = [row for row in documents() if row[1] == day]
    if not records:
        return
    reason = (
        CHANGES[day][2]
        if day in CHANGES
        else "本班集中签收客户续期与备选安排，请核对各册签署状态。"
    )
    for site in REGISTERS:
        lines = [f"{site}联席纪要　六月{day}日签发", reason]
        for serial, _, start, end, case, signer, status, qty, rank in records:
            if world.INFO[case][1] != site:
                continue
            lines.append(f"\n议案 {serial}　客户 {case}")
            codes = desk_codes(site, day)
            # Other departments have genuine but distinct dates and obligations.
            entries = [
                (codes[0], signer, status, start, end, qty, rank),
                (
                    codes[1],
                    "本部",
                    "正本",
                    start,
                    end,
                    1 + (qty + 3) % 9,
                    1 + (rank + 1) % 5,
                ),
                (
                    codes[2],
                    "本部",
                    "正本",
                    start,
                    min(end, start + 1),
                    2 + qty % 4,
                    1 + (rank + 2) % 5,
                ),
            ]
            offset = (serial // 10 + day + serial % 10) % 3
            parent = parent_serial(day, world.IDS.index(case))
            for pos, (code, owner, kind, first, last, seats, order) in enumerate(
                entries[offset:] + entries[:offset]
            ):
                if parent is not None:
                    lines.append(
                        f"{code}册｜续签沿用流水{parent}同一业务的额度。六月{first}日至{last}日采用优先号{order}；签发：{owner}，{kind}。"
                    )
                    continue
                formats = (
                    f"{code}册｜{owner}出具{kind}。六月{first}日至{last}日，核给{seats}席，按优先号{order}排队。",
                    f"{code}册｜办理顺位{order}，额度{seats}席；仅在六月{first}日至{last}日适用。签发：{owner}，{kind}。",
                    f"{code}册｜六月{first}日至{last}日的留位为{seats}席（优先号{order}）。本栏由{owner}签发，状态为{kind}。",
                )
                lines.append(formats[pos])
        put(folder, site + "联席纪要.txt", "\n".join(lines) + "\n")


def retired_names(day):
    name = "分册登记簿.txt" if day == 2 else "换册交接单.txt"
    return [name, *(site + "联席纪要.txt" for site in REGISTERS)]
