"""Read only issued text and test business mistakes on the real desk and frozen snapshots."""

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from tasks.w4.grade import grade


class BulletinReader:
    def __init__(self):
        self.registers = {}
        self.changes = {}
        self.seats = {}

    def read(self, folder, day, mode):
        for name in ("分册登记簿.txt", "换册交接单.txt"):
            path = folder / name
            if not path.exists() or (mode == "stale_register" and day == 7):
                continue
            lines = path.read_text().splitlines()
            effective = (
                int(re.match(r"六月(\d+)日起", lines[0])[1]) if day == 7 else day
            )
            for line in lines[1:]:
                station, onsite, shuttle = re.match(
                    r"(.+)：现场预约用(.)册，接驳预约用(.)册，", line
                ).groups()
                self.changes[(effective, station)] = (onsite, shuttle)
        for (effective, station), codes in sorted(self.changes.items()):
            if effective <= day:
                self.registers[station] = codes
        result = []
        for path in sorted(folder.glob("*联席纪要.txt")):
            site = path.name.removesuffix("联席纪要.txt")
            onsite, shuttle = self.registers[site]
            for line in path.read_text().splitlines():
                if line.startswith("议案 "):
                    serial, case = re.fullmatch(
                        r"议案 (\d+)　客户 (J\d+)", line
                    ).groups()
                    continue
                if not line.startswith(
                    (shuttle if mode == "wrong_desk" else onsite) + "册｜"
                ):
                    continue
                if mode == "ignore_updates" and day not in (2, 7):
                    continue
                start, end = re.search(r"六月(\d+)日至(\d+)日", line).groups()
                parent = re.search(r"沿用流水(\d+)", line)
                if parent and mode == "skip_references":
                    continue
                seats = (
                    self.seats[parent[1]] if parent else re.search(r"(\d+)席", line)[1]
                )
                self.seats[serial] = seats
                priority = re.search(r"(?:优先号|顺位)(\d+)", line)[1]
                result.append(
                    {
                        "流水": serial,
                        "案号": case,
                        "签发日": str(day),
                        "生效日": start,
                        "到期日": end,
                        "额度": seats,
                        "优先号": priority,
                        "签发人": re.search("本部|代办", line)[0],
                        "性质": re.search("待批|正本|草案", line)[0],
                    }
                )
        return result


def compare():
    from .quota_controls import play

    with TemporaryDirectory() as td:
        for mode in (
            "gold",
            "skip_references",
            "ignore_updates",
            "wrong_desk",
            "stale_register",
            "latest",
            "empty",
        ):
            run = Path(td) / mode
            play(run, mode, promise=True, mixed=True)
            result = grade(run)
            print(
                json.dumps(
                    {
                        "strategy": mode,
                        "points": result["total"],
                        **result["fulfilment"],
                        "format_issues": len(result["format_issues"]),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    compare()
