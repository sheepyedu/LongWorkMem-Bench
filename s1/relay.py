"""Seeded card-league equipment relay: notices, handovers and irrevocable bookings."""
from dataclasses import dataclass
from random import Random
import json
import re

# Capacity counts Unicode characters. Even the largest tier admits a lossless compact
# roster and its amendments; the controller always returns the actually retained note.
LEVELS = {1: (6, 620), 2: (14, 420), 3: (24, 420), 4: (36, 480)}
FIELDS = ("器材", "箱签", "领牌员", "交接台")
VALUES = (("P1", "P4", "F1", "F4"), tuple(f"{i:02}" for i in range(10, 100)),
          tuple("松柏杉榆柳槐桃杏"), tuple("东西南北"))
WEIGHTS = {4: 20, 5: 15, 7: 40, 8: 25}
PHASE = {4: "预选", 5: "邀请", 7: "决赛"}


@dataclass(frozen=True)
class Notice:
    number: str
    team: str
    field: int
    value: str
    scope: str
    turn: int
    official: bool


class Season:
    def __init__(self, seed, level, variant="A", edition="original"):
        if level not in LEVELS or variant not in ("A", "B") or edition not in ("original", "warehouse"):
            raise ValueError("invalid scenario")
        self.edition = edition
        self.seed, self.level, self.variant = seed, level, variant
        n, self.capacity = LEVELS[level]
        rng = Random(f"relay/v1/{seed}")
        self.teams = [f"{i:02}" for i in rng.sample(range(10, 100), n)]
        self.base = {k: [rng.choice(v) for v in VALUES] for k in self.teams}
        self.flip = {}
        # A/B differ only in opening equipment allocations. Subsequent notices and
        # the physical draw must be identical, even if an update shadows an opening.
        for k in self.teams[::2]:
            initial = self.base[k][0]
            self.flip[k] = initial.replace("P", "x").replace("F", "P").replace("x", "F")
        if edition == "warehouse":
            # Both opening histories inherit the same older inventory slip.
            stock_rng = Random(f"warehouse/v1/{seed}")
            self.stock = {team: list(row) for team, row in self.base.items()}
            for team in self.teams:
                field = stock_rng.randrange(4)
                domain = [v for v in VALUES[field] if v != self.base[team][field]]
                self.stock[team][field] = stock_rng.choice(domain)
        if variant == "B":
            for team, kit in self.flip.items():
                self.base[team][0] = kit
        self.notices = []
        self.withdrawn = {}
        for turn, scope, count in [(2, "全季", n), (2, "决赛", n // 2),
                                   (3, "邀请", n), (3, "全季", n // 2),
                                   (6, "决赛", n), (6, "全季", n // 2)]:
            for team in rng.sample(self.teams, count):
                field = rng.randrange(4)
                self.notices.append(Notice(f"D{len(self.notices)+1:03}", team, field,
                                           rng.choice(VALUES[field]), scope, turn, rng.random() >= .2))
        for t in (3, 6):
            prior = [d for d in self.notices if d.turn < t and d.official and d.number not in self.withdrawn]
            for d in rng.sample(prior, max(1, n // 4)):
                self.withdrawn[d.number] = t
        self.jobs = {}
        for turn in WEIGHTS:
            count = min(n, max(4, n // 2))
            subset = rng.sample(self.teams, count)
            self.jobs[turn] = [(team, PHASE.get(turn) or ("预选" if i % 2 == 0 else "邀请"))
                               for i, team in enumerate(subset)]
        self.bulletins = {1: "开幕领用册（队号 器材 箱签 领牌员 交接台）：\n" +
                          "\n".join(" ".join([k, *v]) for k, v in self.base.items())}
        for turn in (2, 3, 6):
            changes = [f"{d.number} {'批准' if d.official else '草案'} {d.scope} 队{d.team} "
                       f"{FIELDS[d.field]}={d.value}" for d in self.notices if d.turn == turn]
            changes.extend("撤回 " + num for num, t in self.withdrawn.items() if t == turn)
            self.bulletins[turn] = "本班收文（本批撤回以所列原单号为准）：\n" + "\n".join(changes)

    def prompt(self, turn, note, condition, briefings=()):
        label = {1: "接收开幕册", 2: "受理俱乐部变更", 3: "邀请赛前点交",
                 4: "预选配发", 5: "临时邀请赛配发", 6: "决赛前复核",
                 7: "封存决赛出战器材", 8: "补办历史交接凭证"}[turn]
        instruction = f"第{turn}班·{label}。交接簿限{self.capacity}个字符，当前留存：\n{note or '（空）'}"
        if briefings:
            instruction += "\n档案员补发已公开的原件：\n" + "\n".join(self.bulletins[t] for t in briefings)
        if turn in self.bulletins:
            instruction += "\n" + self.bulletins[turn] + "\n本班仅登记收文，无需配发。"
        else:
            instruction += "\n本次订单（依次为队号、取用哪个赛段的生效配置）：\n" + "、".join(
                f"{team}/{phase}" for team, phase in self.jobs[turn])
            if self.edition == "warehouse":
                instruction += "\n季前仓单（队号 器材 箱签 领牌员 交接台；仅供核对，可能早在开幕时就已变动）：\n" + "\n".join(
                    " ".join([team, *self.stock[team]]) for team, _ in self.jobs[turn])
        return instruction

    def expected(self, team, phase):
        cutoff = {"预选": 4, "邀请": 5, "决赛": 7}[phase]
        values = list(self.base[team])
        for d in self.notices:
            if (d.team == team and d.official and d.turn <= cutoff and
                    self.withdrawn.get(d.number, 99) > cutoff and d.scope in ("全季", phase)):
                values[d.field] = d.value
        return values


RULES = """你是卡牌联赛的随队器材领队。每队一套配置，顺序固定为[器材,箱签,领牌员,交接台]。
P/F分别为对子/同色，1/4分别为一次/持续装；领队必须按已批准的配置真实配发。
开幕册为底。只采纳批准单，忽略草案。全季单自发布起适用所有场次；专项单只适用指定赛段。对同队同字段，在适用的批准单里按单号取最新值。撤回从公布时起排除该单，回退到剩余有效单或底册，不追溯已结束的场次。
第4班预选，第5班邀请，第7班决赛，第8班按订单所列当时赛段重建历史凭证（以第4或第5班当时的有效授权为准，即使那时未实际订购该队）。
届时系统才抽出所需队伍。每班用一个 JSON 对象提交，例如 {"note":"交接簿全文","orders":{"12":["P4","38","松","北"]}}。无订单时 orders 可省略。
订单一经提交就实际配发；赛后统一验收。note 可用任何紧凑编码；覆盖旧簿，超长仅留前段，省略原样保留。请直接提交，无需复述。"""
WAREHOUSE_RULES = RULES.replace(
    '例如 {"note":"交接簿全文","orders":{"12":["P4","38","松","北"]}}',
    '顶层 note 为交接簿全文，orders 为对象，以本班订单里的队号作键，值是四项实际配置的 JSON 数组'
) + "每次订单附同队季前仓单供核对，开幕领用册和其后生效的批准始终优先。换班后不能按单号调档。四项齐全的单据逐队受理，器材与箱签决定上桌验收，领牌员与交接台决定送达验收。"
HANDOVER = "第4、7、8班开班时换人，只有交接簿随队，其余班沿用当前会话。"
CONTINUOUS = "八班由同一人连续值班，保留本赛季对话。"


def unique_fields(pairs):
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("重复字段")
    return data


def decode(text):
    """Allow ordinary Markdown wrapping. Never silently pick one of two submissions."""
    chunks = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    candidates = chunks if chunks else [text.strip()]
    decoded = []
    for part in candidates:
        try:
            obj = json.loads(part.strip(), object_pairs_hook=unique_fields)
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict):
            decoded.append(obj)
    if len(decoded) != 1:
        raise ValueError("请只交一个完整 JSON 对象，队号作键")
    return decoded[0]


def submit(season, turn, reply, old_note):
    note = reply.get("note", old_note)
    orders = reply.get("orders", {})
    if not isinstance(note, str) or not isinstance(orders, dict):
        raise ValueError("note 须为文字，orders 须为对象")
    allowed = dict(season.jobs.get(turn, []))
    booked, rejected = {}, []
    for team, row in orders.items():
        if team not in allowed or not isinstance(row, list) or len(row) != 4:
            rejected.append(team)
            continue
        fields = [str(x).strip() for x in row]
        if season.edition == "original" and any(value not in domain for value, domain in zip(fields, VALUES)):
            rejected.append(team)
            continue
        booked[team] = fields
    return {"turn": turn, "note": note[:season.capacity], "note_length": len(note),
            "booked": booked, "rejected": rejected}


def grade(season, receipts):
    details, groups = [], {}
    for turn, weight in WEIGHTS.items():
        booked = receipts.get(str(turn), {}).get("booked", {})
        hits = 0
        for team, phase in season.jobs[turn]:
            correct = season.expected(team, phase)
            actual = booked.get(team)
            kit = bool(actual and actual[:2] == correct[:2])
            delivery = bool(actual and actual[2:] == correct[2:])
            hits += kit + delivery
            details.append(dict(turn=turn, team=team, phase=phase, expected=correct,
                                actual=actual, kit=kit, delivery=delivery))
        groups[str(turn)] = weight * hits / (2 * len(season.jobs[turn]))
    return {"total": round(sum(groups.values()), 3), "groups": groups, "rows": details}
