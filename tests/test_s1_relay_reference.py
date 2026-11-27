"""An observation-only reference captain, including actual serialization at handover."""
import base64
from itertools import groupby
import re
import struct
import unittest

from s1.relay import FIELDS, LEVELS, PHASE, VALUES, Season, grade, submit


def pack_roster(teams, sheets):
    data = bytearray([len(teams), len(sheets)])
    for team in teams:
        data.append(int(team))
        for sheet in sheets:
            kit, box, captain, desk = [domain.index(x) for domain, x in zip(VALUES, sheet[team])]
            data.extend(struct.pack(">H", ((kit * 90 + box) * 8 + captain) * 4 + desk))
    return data


def unpack_roster(data):
    n, count = data[:2]
    teams, sheets = [], [{} for _ in range(count)]
    pos = 2
    for _ in range(n):
        team = f"{data[pos]:02}"
        pos += 1
        teams.append(team)
        for sheet in sheets:
            value = int.from_bytes(data[pos:pos + 2], 'big')
            pos += 2
            value, desk = divmod(value, 4)
            value, captain = divmod(value, 8)
            kit, box = divmod(value, 90)
            sheet[team] = [domain[i] for domain, i in zip(VALUES, (kit, box, captain, desk))]
    return teams, sheets, pos


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


def handover_archive(teams, base, records, revocations):
    raw = pack_roster(teams, [base])
    groups = [(k, list(group)) for k, group in groupby(records, key=lambda row: row[:2])]
    raw.append(len(groups))
    for (turn, scope), rows in groups:
        raw.extend([turn, scope, len(rows)])
        for _, _, team, field, value, official in rows:
            item = ((teams.index(team) * 4 + field) * 128 + value) * 2 + int(official)
            raw.extend(struct.pack(">H", item))
    raw.extend([len(revocations)])
    for key, turn in revocations.items():
        raw.extend([key, turn])
    return base64.b85encode(raw).decode()


def restore_archive(note):
    data = base64.b85decode(note)
    teams, (base,), pos = unpack_roster(data)
    records, revoked = [], {}
    groups = data[pos]
    pos += 1
    for _ in range(groups):
        turn, scope, count = data[pos:pos+3]
        pos += 3
        for _ in range(count):
            v = int.from_bytes(data[pos:pos+2], 'big')
            pos += 2
            v, ok = divmod(v, 2)
            v, value = divmod(v, 128)
            idx, field = divmod(v, 4)
            records.append((turn, scope, teams[idx], field, value, bool(ok)))
    for i in range(data[pos]):
        number, turn = data[pos+1+2*i:pos+3+2*i]
        revoked[number] = turn
    return teams, base, records, revoked


def rosters(base, records, revoked):
    result = {}
    for stage, name in PHASE.items():
        sheet = {team: list(row) for team, row in base.items()}
        for number, (turn, scope, team, field, val, approved) in enumerate(records, 1):
            if approved and turn < stage and revoked.get(number, 99) > stage and SCOPE[scope] in ("全季", name):
                sheet[team][field] = VALUES[field][val]
        result[name] = sheet
    return result


class PublicReferenceTest(unittest.TestCase):
    def test_solve_with_only_previously_public_bulletins_inside_actual_capacity(self):
        for level in LEVELS:
            for seed in range(12):
                for arm in "AB":
                    season = Season(seed, level, arm)
                    rows = [line.split() for line in season.bulletins[1].splitlines()[1:]]
                    base = {team: fields for team, *fields in rows}
                    teams = list(base)
                    records, revoked = [], {}
                    for t in (2, 3):
                        read_notices(season.bulletins[t], records, revoked, t)
                    note = handover_archive(teams, base, records, revoked)
                    self.assertLessEqual(len(note), season.capacity)
                    teams, base, records, revoked = restore_archive(note)
                    sheets = rosters(base, records, revoked)
                    receipts = {}
                    def book(t):
                        orders = {team:sheets[phase][team] for team,phase in season.jobs[t]}
                        receipts[str(t)] = submit(season, t, {"orders":orders}, "")
                    book(4)
                    book(5)
                    read_notices(season.bulletins[6], records, revoked, 6)
                    sheets = rosters(base, records, revoked)
                    note = base64.b85encode(pack_roster(teams, list(sheets.values()))).decode()
                    self.assertLessEqual(len(note), season.capacity)
                    for t in (7, 8):
                        _, restored, _ = unpack_roster(base64.b85decode(note))
                        sheets = dict(zip(PHASE.values(), restored))
                        book(t)
                    self.assertEqual(grade(season, receipts)["total"], 100)
