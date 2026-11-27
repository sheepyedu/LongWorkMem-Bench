"""Independent reconstruction of rosters from public circuit bulletins."""
import re

from tasks.s1.relay import FIELDS, PHASE, VALUES

SCOPE = ("全季", "邀请", "决赛")


def read_notices(text, records, revocations, turn):
    for line in text.splitlines()[1:]:
        if line.startswith("撤回 "):
            revocations[int(line.split("D")[1])] = turn
            continue
        number, official, scope, team, field, val = re.fullmatch(
            r"D(\d+) (批准|草案) (\S+) 队(\d+) (\S+)=(\S+)", line).groups()
        assert int(number) == len(records) + 1
        i = FIELDS.index(field)
        records.append((turn, SCOPE.index(scope), team, i, VALUES[i].index(val), official == "批准"))


def rosters(base, records, revoked):
    result = {}
    for stage, name in PHASE.items():
        sheet = {team: list(row) for team, row in base.items()}
        for number, (turn, scope, team, field, val, approved) in enumerate(records, 1):
            if approved and turn < stage and revoked.get(number, 99) > stage and SCOPE[scope] in ("全季", name):
                sheet[team][field] = VALUES[field][val]
        result[name] = sheet
    return result
