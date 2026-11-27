"""July settlement documents and author-side interfaces for the advanced W1 office."""
from decimal import Decimal
from pathlib import Path
import random

from .world import _csv, _mail, _text


CENT = Decimal(".01")
BUDGET_FIELDS = "document,revision,project,operation,amount,decision,signed"
TIME_FIELDS = "site,ticket,revision,employee,worked,project,units,unit,decision,posted"


def staff(level):
    return [f"E{i:02}" for i in range(1, (12 if level == 1 else 24) + 1)]


def office_setup(work, level):
    directory = work / "input/薪酬制度"
    _csv(directory / "人员台账.csv", "employee,home", [
        (e, "甲" if e == "E07" or i % 2 == 0 else "乙") for i, e in enumerate(staff(level))])
    _text(directory / "运营签收本.txt", """
人力与财务现场操作规程（2025-06-01 生效）
额度结算只使用本期签发登记。按本地时间 7 月 31 日 18:00 截止，同一 document 的正式签发或撤销取最大 revision；草拟或截止后签署的版本不取代此前有效版本。撤销的整份文件失效。操作“额度”为项目基数，“调增”为有符号调整，预算有数不等于可放行，应以财务正式放行函为准。
工时结算截止为 8 月 3 日 18:00（含）。东、西厂的 ticket 各自编号。合并工时中心主账与补正，同一厂票只取截止前已核或作废的最高整版 revision，再剔除已作废和实际发生日不在七月的票。待核或迟到的高版不废止旧的已核版。重复导出的同一版只入一次。H 是小时，MIN 是分钟。
已指明项目的票照原项目。共享工时按实际工作日和当日有效的人事批件归属，平时按人员台账。项目写“待查”的有效票不进工资，按厂、票号登工时待查表，每厂同号分列；待批项目不属待查票。无核准正工时的员工项目组合不列。
金额以元计到分，每项目按核准工时比例先逐人向下截到分，再把剩余分币全给工时最多者（并列给员工号字符序最小者）。示例：池 10.00 元、三人各 1 小时，金额为 3.34、3.33、3.33。交付文件使用 UTF-8 CSV，含表头。
""")
    if level == 2:
        _text(directory / "现场补充条款-06.txt", """
经会签的定向值班单仅覆盖单内人员、工作日期（含两端）及共享工时，优先于人事常设批件；指定项目的工时不受其影响。
已放行项目每项可有一名受合同上限约束的员工。先用未截分的比例份额判断是否达到个人上限（达到也按限额处理）；触限者按上限列支，项目剩余池只在其余员工间按工时重新分配，截分后的全部尾差只给参与此次剩余池分配者中的工时最高者，并列仍按员工号升序。未触限按常规算法；若尾差加给常规赢家会越过上限，按触限处理再分。变动工时或池额后，上限判断随之重算。
""")
    for month in ("04", "05", "06"):
        _csv(work / f"input/薪酬归档/2025-{month}/临时统计.csv", "employee,month,hours,project",
             [(e, f"2025-{month}", 12 + i % 23, "乙" if i % 2 else "甲") for i, e in enumerate(staff(level))])


def publish_budget(work, level, seed):
    gen = random.Random(seed + 30211)
    rows = []
    for i, project in enumerate("甲乙丙"):
        base = Decimal(gen.randrange(850003, 1100700)) * CENT
        code = f"F-{401 + i}"
        rows.extend([
            (code, 1, project, "额度", base, "签发", "2025-07-22 10:00"),
            (code, 2, project, "额度", base + 90, "草拟", "2025-07-30 08:00"),
            (f"P-{31+i}", 1, project, "调增", gen.randint(103, 304), "签发", "2025-07-25 16:00"),
            (f"P-{31+i}", 2, project, "调增", -gen.randint(42, 100), "签发", "2025-07-31 18:00"),
        ])
        if level == 2:
            rows.extend([
                (f"W-{31+i}", 1, project, "调增", 155, "签发", "2025-07-28 12:00"),
                (f"W-{31+i}", 2, project, "调增", 155, "撤销", "2025-07-31 17:58"),
                (code, 3, project, "额度", base + 500, "签发", "2025-07-31 18:03"),
                (f"P-{31+i}", 3, project, "调增", 120, "撤销", "2025-08-01 08:08"),
            ])
    gen.shuffle(rows)
    _csv(work / "input/财务会签/额度签署登记.csv", BUDGET_FIELDS, rows)
    _mail(work, "FN-F72", "2025-08-01", "finance", "F-72｜七月项目批复",
          "本期书面放行项目：甲、乙。丙仍待签、留待下批。按月末结账截点采用已签额度和生效调整。")
    if level == 2:
        _csv(work / "input/财务会签/个人合同上限.csv", "project,employee,cap", [
            ("甲", "E03", Decimal(gen.randrange(14000, 19000))*CENT),
            ("乙", "E09", Decimal(gen.randrange(78000, 83000))*CENT)])


def publish_times(work, level, seed):
    gen = random.Random(seed + 45061)
    people = staff(level)
    primary, patch = [], []
    count = 182 if level == 1 else 556
    for index in range(count):
        site = ("东厂", "西厂")[index % 2]
        ticket = f"T-{1001 + index // 2}"
        employee = people[index % len(people)]
        project = gen.choice(("甲", "乙", "共享", "共享", "丙"))
        if index % 53 == 2:
            project = "待查"
        day = f"2025-07-{gen.randint(1,31):02}"
        unit = "MIN" if index % 3 else "H"
        amount = gen.randint(1, 12) * (15 if unit == "MIN" else Decimal(".25"))
        original = [site, ticket, 1, employee, day, project, amount, unit, "已核", "2025-07-31 16:00"]
        if level == 2 and index % 35 == 1:
            original[4] = "2025-06-30"
        primary.append(original)
        if index % 9 == 2:
            patch.append(original.copy())
        if index % 13 == 3:
            patch.append([*original[:2], 2, *original[3:6], amount * 2, unit, "已核", "2025-08-03 18:00"])
        if index % 17 == 9:
            patch.append([*original[:2], 3, *original[3:8], "作废", "2025-08-03 15:45"])
        if index % 19 == 5:
            patch.append([*original[:2], 4, *original[3:6], amount * 5, unit, "待核", "2025-08-03 16:15"])
        if level == 2 and index % 23 == 8:
            patch.append([*original[:2], 5, *original[3:6], amount * 3, unit, "已核", "2025-08-03 18:01"])
    # A July mid-month change must matter for every seed, even when a local duty order is active.
    for ix, (emp, project, day, h) in enumerate([
            ("E07","共享","2025-07-15", 3), ("E07","共享","2025-07-16", 4),
            ("E07","共享","2025-07-30", 7), ("E07","甲","2025-07-18", 2),
            ("E07","乙","2025-07-13", 2), ("E03","甲","2025-07-21", 12),
            ("E09","乙","2025-07-21", 2)]):
        primary.append(["东厂",f"X-{ix+1}",1,emp,day,project,h,"H","已核","2025-07-31 16:00"])
    gen.shuffle(primary)
    gen.shuffle(patch)
    _csv(work / "input/工时中心/主账.csv", TIME_FIELDS, primary)
    _csv(work / "input/工时中心/补正.csv", TIME_FIELDS, patch)


def release(work: Path, turn: int, variant: str, level: int, seed: int) -> str:
    if turn == 1:
        office_setup(work, level)
    elif turn == 2:
        effective = {"A": "2025-07-16", "B": "2025-08-16"}[variant]
        _mail(work, "HR-0628", "2025-06-28", "hr", "HR-46B｜共享支援归口变更",
              f"签发：员工 E07，共享支援由甲转乙，生效日 {effective}（含当日）。指定项目工时仍按登记。")
    elif turn == 4 and level == 2:
        _csv(work / "input/人事值班/签批派班.csv", "employee,from,to,project", [
            ("E07","2025-07-21","2025-07-26","丙"), ("E11","2025-07-10","2025-07-23","乙"),
            ("E12","2025-07-17","2025-07-29","甲"), ("E19","2025-07-08","2025-07-19","乙")])
    elif turn == 6:
        publish_budget(work, level, seed)
        return ("财务七月会签件已入盘，结合此前经办事项，按书面范围及结账截点核定本次可结项目和可用额度，"
                "交 out/released.csv（project,pool）。待签的继续留待下批。")
    elif turn == 7:
        publish_times(work, level, seed)
        return ("七月工时双方已移交，依本期放行和在办人事、薪酬制度办理实发。"
                "交 out/pay.csv（project,employee,hours,bonus）和 out/time_review.csv（site,ticket），"
                "另交 out/bonus.xlsx，Pools 页 project,pool，Pay 页 project,employee,hours,bonus。"
                "财务改任一现有行的正工时或正数奖金池后，个人奖金和项目合计须按同一办法自动重算。")
    return ""


def expected_pay(variant, level, seed):
    from .advanced_pay_checks import pristine
    return pristine(variant, level, seed)["pay"]


def reference(run, turn, variant, level, seed):
    from .advanced_pay_checks import solve
    if turn in (6, 7):
        solve(run / "work", turn, level)


def checks(run, variant, level, seed):
    from .advanced_pay_checks import grade
    return grade(run, variant, level, seed)
