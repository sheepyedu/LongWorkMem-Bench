"""Independent public-material operator and reduced strategies; never reads scorer targets."""

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from tasks.w1.runstate import freeze, prepare
from tasks.w4.office import invoke
from tasks.w4.quota import world as w


def records(p):
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write(root, name, cols, rows):
    w.csvfile(root / (name + ".csv"), ",".join(cols), rows)


def play(run, mode="gold"):
    work = prepare(run)
    w.initialize(work)
    (run / "manifest.json").write_text('{"protocol":"w4-release-v4"}')
    d = work / "input/站务"
    out = work / "out"
    charter = {r["案号"]: r for r in records(d / "章程.csv")}
    ids = sorted(charter)
    papers = []
    withdraw = set()
    delegates = {}
    coupons = {}
    void = set()
    third = {}

    def query(t, case="", cut="", receipt=""):
        data = invoke(
            run,
            t,
            None,
            "receipt_query",
            dict(case=case, as_of=str(cut), receipt=receipt),
        )
        return data if receipt else {x["案号"]: x for x in data}

    def send(t, subject, recipient, file):
        return invoke(
            run,
            t,
            None,
            "deliver",
            dict(subject=subject, recipient=recipient, attachment="out/" + file),
        )["receipt"]

    def pick(k, t):
        ch = charter[k]
        opts = [(0, 0, "章程", int(ch["章程额度"]), int(ch["章程优先号"]))]
        for r in papers:
            if r["案号"] != k:
                continue
            serial = int(r["流水"])
            if mode != "latest":
                if (
                    not int(r["生效日"]) <= t <= int(r["到期日"])
                    or r["性质"] != "正本"
                    or serial in withdraw
                ):
                    continue
                if mode == "opening" and r["签发日"] != "2":
                    continue
                if r["签发人"] == "代办":
                    v = delegates[ch["站"]]
                    if not (
                        ch["对象"].endswith(v["代办系列"])
                        and int(v["开始"]) <= t <= int(v["末日"])
                    ):
                        continue
            opts.append(
                (
                    int(r["生效日"]),
                    serial,
                    str(serial),
                    int(r["额度"]),
                    int(r["优先号"]),
                )
            )
        return max(opts)[2:]

    def claim(k, t):
        if not coupons or mode == "opening":
            return 0
        r = coupons[k]
        if k in void or not int(r["生效日"]) <= t <= int(r["末日"]):
            return 0
        return min(
            int(r["转入上限"]), max(0, int(r["保证基数"]) - third[r["来源案"]]["实占"])
        )

    def allocate(kday, opening):
        facts = {k: pick(k, kday) for k in ids}
        facts = {
            k: (
                doc,
                base,
                claim(k, kday),
                base + claim(k, kday),
                rank - int(claim(k, kday) > 0),
            )
            for k, (doc, base, rank) in facts.items()
        }
        q = (
            sorted(ids, key=lambda k: (facts[k][-1], k))
            if mode != "arrival"
            else list(ids)
        )
        free = {}
        net = {}
        allocated = {}
        for p in w.POOLS:
            group = [k for k in q if charter[k]["站"] == p]
            capacity = opening[group[0]]["本站容量"]
            free[p] = capacity - sum(opening[k]["锁定"] for k in group)
            remaining = free[p]
            for k in group:
                lock = opening[k]["锁定"]
                net[k] = max(0, facts[k][3] - lock)
                n = min(net[k], remaining)
                allocated[k] = n + lock
                remaining -= n
        return facts, q, free, net, allocated

    for day in range(1, 13):
        w.release(work, day)
        inc = work / "inbox" / f"06-{day:02}"
        if (inc / "签发原件.csv").exists():
            papers += records(inc / "签发原件.csv")
        if (inc / "撤文.csv").exists():
            withdraw.update(
                int(r["当日生效撤销流水"]) for r in records(inc / "撤文.csv")
            )
        if day == 2:
            coupons = {r["兑现案"]: r for r in records(inc / "续办券.csv")}
        if day > 3:
            third = query(day, cut=3)
        if (inc / "注销券.csv").exists():
            void.update(r["兑现案"] for r in records(inc / "注销券.csv"))
        if day == 6:
            delegates = {r["站"]: r for r in records(inc / "委托.csv")}
        opening = query(day, "开班")
        current = opening
        if mode == "empty":
            freeze(run, day, rounds=range(1, 13))
            continue
        if day in (3, 9, 10, 11, 8, 12):
            facts, q, free, net, target = allocate(9 if day == 8 else day, opening)
        if day in (3, 9, 10, 11):
            for attempt in range(4):
                changed = [k for k in ids if current[k]["实占"] != target[k]]
                if not changed:
                    break
                order = sorted(
                    changed, key=lambda k: (target[k] > current[k]["实占"], k)
                )
                write(
                    out,
                    "申请",
                    ("案号", "请求号", "预期版本", "目标席"),
                    [
                        (k, f"{day}-{attempt}-{k}", current[k]["版本"], target[k])
                        for k in order
                    ],
                )
                receipt = send(day, "站务申请", "quota@office.test", "申请.csv")
                if mode == "ignore_feedback":
                    # Assume the submitted absolute target was applied in full.
                    current = {k: dict(v) for k, v in current.items()}
                    for i, k in enumerate(order, 1):
                        current[k].update(
                            实占=target[k],
                            版本=current[k]["版本"] + 1,
                            最后受理号=receipt + "/" + str(i),
                        )
                    break
                query(day, receipt=receipt)
                current = query(day)
            write(
                out,
                "调度",
                ("案号", *w.DISPATCH),
                [
                    (
                        k,
                        *facts[k],
                        target[k],
                        current[k]["实占"],
                        current[k]["最后受理号"],
                    )
                    for k in ids
                ],
            )

        def mail(k, why):
            code = charter[k]["对象"][:2]
            return (
                code.lower()
                + (".review" if code in ("HZ", "NP", "BA") and why else ".service")
                + "@office.test"
            )

        rows = []
        for k in ids:
            ch = charter[k]
            p = ch["站"]
            s = opening[k]
            if day == 1:
                v = [ch["期初实占"], ch["期初锁定"], ch["章程额度"]]
            elif day == 2:
                v = pick(k, 3)
            elif day == 4:
                v = [query(day, cut=3)[k]["实占"], s["实占"], s["版本"]]
            elif day == 5:
                v = [mail(k, True), mail(k, False)]
            elif day == 6:
                v = [delegates[p]["代办系列"], delegates[p]["末日"]]
            elif day == 7:
                v = [
                    pick(k, 9)[0],
                    pick(k, 10)[0],
                    third[coupons[k]["来源案"]]["实占"],
                    claim(k, 9),
                ]
            elif day == 11:
                change = target[k] != s["实占"]
                need = change or k in [x["案号"] for x in records(inc / "主动询证.csv")]
                prev = query(day, cut=10)[k]["实占"]
                v = [
                    query(day, cut=3)[k]["实占"],
                    prev,
                    s["实占"],
                    target[k],
                    "解释" if change else "维持" if need else "无",
                ]
                if need:
                    write(
                        out,
                        "通知",
                        ("案号", "十日实占", "今日目标", "办后实占"),
                        [(k, prev, target[k], current[k]["实占"])],
                    )
                    send(day, k, mail(k, change), "通知.csv")
            elif day == 12:
                v = [s["实占"], s["版本"], s["最后受理号"]]
            else:
                continue
            rows.append((k, *v))
        if day in w.FILES:
            n, cols = w.FILES[day]
            write(out, n, ("案号", *cols), rows)
        if day in (8, 12):
            book = load_workbook(out / "预约.xlsx")
            s = book["队列"]
            for i, p in enumerate(w.POOLS, 2):
                book["容量"].cell(i, 2).value = free[p]
            for i, k in enumerate(q, 2):
                for j, v in enumerate((k, charter[k]["站"], net[k]), 1):
                    s.cell(i, j).value = v
                past = "0" if i == 2 else f"SUMIF(B$2:B{i - 1},B{i},D$2:D{i - 1})"
                s.cell(
                    i, 4
                ).value = f"=MIN(C{i},MAX(0,VLOOKUP(B{i},容量!A$2:B$5,2,0)-{past}))"
                s.cell(i, 5).value = f"=C{i}-D{i}"
            book.save(out / "预约.xlsx")
            book.close()
        freeze(run, day, rounds=range(1, 13))


if __name__ == "__main__":
    from tasks.w4.grade import grade

    with TemporaryDirectory() as td:
        for mode in (
            "gold",
            "latest",
            "opening",
            "arrival",
            "ignore_feedback",
            "empty",
        ):
            p = Path(td) / mode
            play(p, mode)
            g = grade(p)
            print(
                json.dumps(
                    {
                        "mode": mode,
                        "total": g["total"],
                        "rounds": g["rounds"],
                        "atoms": len(g["atoms"]),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
