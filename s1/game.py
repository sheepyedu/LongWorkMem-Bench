"""Deterministic text-card league. Only open_turn, observe and action receipts are player-visible."""
from copy import deepcopy
from itertools import combinations, product
from random import Random

PATTERNS = {"pair": "对子", "flush": "同色组", "single": "单张"}
GEAR = {"pair_repeat": "对子持续装", "pair_once": "对子一次装",
        "flush_repeat": "同色持续装", "flush_once": "同色一次装", "none": "空槽"}
MATCHES = {2: ("main1",), 3: ("main2",), 4: ("invite1", "invite2"),
           5: ("return",), 8: ("free1", "free2")}
NAMES = {"main1": "揭幕站", "main2": "第二站", "invite1": "邀请赛上场",
         "invite2": "邀请赛下场", "return": "主赛第三站", "free1": "自由组首场", "free2": "自由组次场"}
TITLES = ("", "开幕侦察", "揭幕站", "第二站与营地", "邀请赛", "主赛第三站",
          "补给车归队", "决赛报名", "决赛与清算")
PROMPTS = (
    "",
    "你是本队领队。请带队完成整个赛季，赛后用私人现金付 2 金尾款。报到已办妥，现经过侦察站。"
    "可以查看规则、试打一手，也可以自己维护赛季笔记。",
    "请用队伍手里的牌打完揭幕站。赛后从随队卡和现金中选一份奖励。",
    "请打完第二站。补给车随后先行，如果需要，可以当场免费预订一份物资，等回主赛后领取。",
    "俱乐部邀请你代打两场友谊赛，提供借牌。主办方通知：仅本次邀请赛，两场的场地奖都从对子移给同色组，每个同色组额外 4 分。请打完两场。",
    "回主赛，把这一站打完。",
    "决赛补给站已开放。请处理先前的队务，按需领取或购买私人物资，为自由组做好准备。",
    "请在报名台完成两个组别的报名，确认无误后一起锁定。自由组使用自家牌组和库存，统一组使用组委会的租借牌和专用券。",
    "决赛开始。请查收统一组结果，亲自打完自由组的两场比赛，然后用私人现金结清赛季尾款。",
)
RULES = (
    "出牌时选定牌型与牌号：pair 恰两张同点数，flush 恰三张同色，single 一张。"
    "每手只选一种。对子与同色组基础各 4 分，单张 1 分。应用动作立即结算。每手牌独立发放，不能留到下一手。",
    "常规主赛每次对子另得 4 分场地奖。邀请赛依现场条款。每场的手数、累计关口以当前牌桌为准。"
    "未过关也可继续后续赛程。揭幕站和第二站过关各获 1 金。",
    "每场手动比赛可换一次牌：用当前明牌候补替换指定手牌，不花金币，不占正式出牌次数。"
    "随队卡每手补进一次，仅私人主赛与自由组可用。相同数值的不同牌号都是独立牌。",
    "报名两份草案都可反复修改，统一确认后不可再改。标准席位一张器材券只能租一件装备；私人席位只能从已领取或购买的库存选一件，两者独立。",
    "决赛没有场地奖。持续装在每个匹配牌型上加 4；一次装每场仅触发一次，在本场第一次匹配时加 7，下场重新计次。遇到侦察所报的屏蔽时，"
    "对应装备的额外分数为 0，牌型仍能打且基础照计。私人能量剂可在自由组任一正式出牌时使用，一次加 7，全季只消耗一份。",
    "统一组用两手租借牌，队员按已锁装备选择得分最高的合法打法，总计 15 分晋级。"
    "自由组两场各两手，每场累计 15 分晋级。未锁定报名则两席未报，仍可空装打自由场并结清尾款。"
)
STAGE_RULES = {
    2: "过站后可领一份奖励。红5或金7会作为永久随队卡加入后续每手私人牌；或领 2 金。"
       "赛事行程单：自由组每场第二手的常规发牌含两张红牌、一张蓝7，其他花色分散，点数均不相同。",
    3: "打完本站后可预订一份对子一次装、同色一次装或能量剂，也可跳过。订单免费，物资到补给站才可领取。",
    5: "本场累计 12 分过关，主办方另有首手 8 分的开场挑战。",
    6: "已订物资可免费领取，私人商店另售对子持续装、同色持续装，各 4 金。买进库存，报名时再选实际出战的一件。",
    7: "报名接受空槽。统一组只使用下列两手租借牌，同一手可声明一种合法牌型，不可换牌。锁定后将在决赛统一发布赛果。",
}
COMMANDS = {
    "rules": ({"op": "rules"}, "查看常驻规则和当前场次说明"),
    "practice": ({"op": "practice", "pattern": "pair", "cards": ["c1", "c2"]}, "用练习桌的牌号试打一手，练习不消耗资源"),
    "note": ({"op": "note", "text": "自己的记录"}, "保存整本赛季笔记（覆盖旧文，最多一万字）"),
    "read_note": ({"op": "read_note"}, "读回自己的笔记"),
    "play": ({"op": "play", "pattern": "pair", "cards": ["c1", "c2"]}, "示例仅示格式，c1、c2 未必是对子。根据当前手牌选牌型和牌号，提交即结算。自由组可加 tonic:true 使用一份能量剂"),
    "discard": ({"op": "discard", "card": "c1"}, "将指定的一张手牌换成明牌候补"),
    "reward": ({"op": "reward", "choice": "red5"}, "选择 red5 红5、gold7 金7 或 coins 两枚金币"),
    "reserve": ({"op": "reserve", "choice": "tonic"}, "预订 pair_once、flush_once、tonic，或选 none 跳过"),
    "claim": ({"op": "claim"}, "领取营地订单"),
    "buy": ({"op": "buy", "gear": "pair_repeat"}, "花 4 金购入 pair_repeat 或 flush_repeat"),
    "draft": ({"op": "draft", "seat": "private", "gear": "none"}, "修改一席报名。seat 取 standard 或 private；gear 从该席可用装备选择"),
    "lock": ({"op": "lock"}, "一次确认并锁定两席现有草案"),
    "pay": ({"op": "pay"}, "比赛打完后付 2 金赛季尾款"),
}


def scout_notice(variant):
    family = {"A": "对子", "B": "同色组"}[variant]
    return f"决赛裁判侦察通报：本届两组决赛均屏蔽{family}装备的额外加分。该牌型仍可出，基础分照计。"


def _hand(seed, match, number):
    rng = Random(f"card-league-v1/{seed}/{match}/{number}")
    if match.startswith("free") and number == 2:
        a, b, c, d = rng.sample([1, 2, 4, 6, 8, 9, 10], 4)
        cards = [("红", a), ("红", b), ("蓝", 7), ("青", c), ("金", d)]
    else:
        a, b, c, d = rng.sample(range(1, 11), 4)
        primary, other, last = rng.sample(["红", "蓝", "青", "金"], 3)
        cards = [(primary, a), (primary, b), (primary, c), (other, a), (last, d)]
    rng.shuffle(cards)
    return [{"id": f"c{i}", "suit": suit, "rank": rank} for i, (suit, rank) in enumerate(cards, 1)]


def new_game(variant, seed):
    if variant not in ("A", "B") or type(seed) is not int:
        raise ValueError("需要合法赛季配置")
    return {"variant": variant, "seed": seed, "turn": 0, "events": [], "note": "",
            "cash": 5, "bench": None, "reward": None, "order": None, "claimed": False,
            "gears": [], "tonics": 0, "draft": {"standard": "none", "private": "none"},
            "locked": None, "paid": False, "standard_score": None,
            "standard_hands": [_hand(seed, "rental", i) for i in (1, 2)]}


def _event(s, kind, **data):
    s["events"].append({"kind": kind, "turn": s["turn"], **data})


def open_turn(s, turn):
    if type(turn) is not int or not 1 <= turn <= 8 or turn != s["turn"] + 1:
        raise ValueError("轮次必须顺序开放")
    s["turn"] = turn
    _event(s, "open")
    if turn == 8 and s["locked"]:
        gear = s["locked"]["standard"]
        s["standard_score"] = _rental_score(s, gear)
        _event(s, "rental_result", gear=gear, points=s["standard_score"])
    prompt = PROMPTS[turn]
    return prompt + ("\n" + scout_notice(s["variant"]) if turn == 1 else "")


def _size(match):
    return 1 if match.startswith("invite") else 2


def _target(match):
    return 15 if match.startswith("free") else 8 if match.startswith("invite") else 12


def _plays(s, match):
    return [e for e in s["events"] if e["kind"] == "play" and e["match"] == match]


def _active(s):
    for match in MATCHES.get(s["turn"], ()):
        n = len(_plays(s, match))
        if n < _size(match):
            return match, n + 1
    return None


def _table(s, match, number):
    cards = _hand(s["seed"], match, number)
    if s["bench"] and not match.startswith("invite"):
        suit, rank = {"red5": ("红", 5), "gold7": ("金", 7)}[s["bench"]]
        cards.append({"id": "bench", "suit": suit, "rank": rank})
    spare = {"id": "spare", "suit": "银", "rank": cards[0]["rank"]}
    swap = next((e for e in s["events"] if e["kind"] == "discard" and e["match"] == match), None)
    if swap and swap["hand"] == number:
        cards = [spare.copy() if c["id"] == swap["card"] else c for c in cards]
    return {"match": match, "name": NAMES[match], "hand": number, "hands": _size(match),
            "cards": cards, "spare": None if swap else spare, "target": _target(match),
            "earned": sum(p["points"] for p in _plays(s, match))}


def _commands(s):
    names = ["rules", "note", "read_note"]
    turn = s["turn"]
    active = _active(s)
    if turn == 1:
        names.append("practice")
    if active:
        names.append("play")
        if not any(e["kind"] == "discard" and e["match"] == active[0] for e in s["events"]):
            names.append("discard")
    if turn == 2 and not active and s["reward"] is None:
        names.append("reward")
    if turn == 3 and not active and s["order"] is None:
        names.append("reserve")
    if turn == 6:
        if s["order"] not in (None, "none") and not s["claimed"]:
            names.append("claim")
        if s["cash"] >= 4 and len(set(("pair_repeat", "flush_repeat")) - set(s["gears"])):
            names.append("buy")
    if turn == 7 and not s["locked"]:
        names.extend(("draft", "lock"))
    if turn == 8 and not active and not s["paid"] and s["cash"] >= 2:
        names.append("pay")
    return names


def observe(s):
    turn = s["turn"]
    names = _commands(s)
    view = {"venue": TITLES[turn], "cash": s["cash"], "bench": s["bench"], "gears": list(s["gears"]),
            "tonics": s["tonics"], "order": s["order"], "claimed": s["claimed"],
            "commands": [{"example": deepcopy(COMMANDS[k][0]), "use": COMMANDS[k][1]} for k in names]}
    if turn in STAGE_RULES:
        view["notice"] = STAGE_RULES[turn]
    if turn == 1:
        view["practice_cards"] = _practice_cards()
    active = _active(s)
    if active:
        view["table"] = _table(s, *active)
    if turn in (7, 8):
        view["entry"] = {"drafts": s["draft"].copy(), "locked": s["locked"] is not None,
                         "private_options": ["none", *s["gears"]], "standard_options": dict(GEAR),
                         "rental_hands": deepcopy(s["standard_hands"]), "standard_vouchers": 1}
    if turn == 8:
        view.update(paid=s["paid"], rental_points=s["standard_score"])
    view["results"] = [{"match": e["match"], "points": e["points"], "qualified": e["qualified"]}
                       for e in s["events"] if e["kind"] == "result"]
    return view


def _practice_cards():
    return [{"id": "c1", "rank": 2, "suit": "红"}, {"id": "c2", "rank": 2, "suit": "蓝"},
            {"id": "c3", "rank": 5, "suit": "红"}, {"id": "c4", "rank": 7, "suit": "红"}]


def _is_pattern(cards, pattern):
    if pattern == "single":
        return len(cards) == 1
    if pattern == "pair":
        return len(cards) == 2 and cards[0]["rank"] == cards[1]["rank"]
    if pattern == "flush":
        return len(cards) == 3 and len({c["suit"] for c in cards}) == 1
    return False


def _select(available, pattern, ids):
    if not isinstance(pattern, str) or pattern not in PATTERNS:
        raise ValueError("牌型须为 pair、flush 或 single")
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("cards 请提供不重复的当前牌号数组")
    by_id = {c["id"]: c for c in available}
    if any(k not in by_id for k in ids):
        raise ValueError("请使用当前牌桌的牌号")
    picked = [by_id[k] for k in ids]
    if not _is_pattern(picked, pattern):
        raise ValueError("所选牌不符合声明的牌型，操作未提交")
    return picked


def _gear_bonus(variant, gear, pattern, prior_patterns):
    if gear == "none":
        return 0
    family, mode = gear.split("_")
    if family != pattern or family == {"A": "pair", "B": "flush"}[variant]:
        return 0
    if mode == "repeat":
        return 4
    return 0 if pattern in prior_patterns else 7


def _rental_score(s, gear):
    options = []
    for cards in s["standard_hands"]:
        options.append([p for p, size in (("pair", 2), ("flush", 3), ("single", 1))
                        if any(_is_pattern(c, p) for c in combinations(cards, size))])
    return max(sum((1 if p == "single" else 4) + _gear_bonus(s["variant"], gear, p, seq[:i])
                   for i, p in enumerate(seq)) for seq in product(*options))


def _play(s, a):
    match, number = _active(s)
    table = _table(s, match, number)
    pattern = a.get("pattern")
    picked = _select(table["cards"], pattern, a.get("cards"))
    tonic = a.get("tonic", False)
    if type(tonic) is not bool or tonic and (not match.startswith("free") or not s["tonics"]):
        raise ValueError("能量剂限持有时在自由组实际出牌使用，tonic 用布尔值")
    base = 1 if pattern == "single" else 4
    station = extra = 0
    gear = "none"
    if match.startswith("free"):
        gear = (s["locked"] or {}).get("private", "none")
        prior = [e["pattern"] for e in _plays(s, match)]
        extra = _gear_bonus(s["variant"], gear, pattern, prior)
    elif pattern == ("flush" if match.startswith("invite") else "pair"):
        station = 4
    points = base + station + extra + 7 * tonic
    if tonic:
        s["tonics"] -= 1
    breakdown = {"pattern": pattern, "base": base, "station_bonus": station, "gear_bonus": extra,
                 "tonic_bonus": 7 * tonic, "points": points}
    _event(s, "play", match=match, hand=number, available=table["cards"], cards=picked,
           gear=gear, tonic=tonic, **breakdown)
    receipt = {"match": match, "hand": number, **breakdown}
    if number == _size(match):
        total = table["earned"] + points
        qualified = total >= _target(match)
        prize = int(qualified and match in ("main1", "main2"))
        _event(s, "result", match=match, points=total, qualified=qualified, prize=prize)
        s["cash"] += prize
        receipt.update(match_points=total, qualified=qualified, prize=prize)
    return receipt


def _apply(s, a):
    op = a["op"]
    if op == "rules":
        return {"rules": list(RULES), "venue_notice": STAGE_RULES.get(s["turn"], "")}
    if op == "practice":
        chosen = _select(_practice_cards(), a.get("pattern"), a.get("cards"))
        return {"cards": chosen, "practice_points": {"pair": 8, "flush": 4, "single": 1}[a["pattern"]]}
    if op == "read_note":
        return {"note": s["note"]}
    if op == "note":
        value = a.get("text")
        if not isinstance(value, str) or len(value) > 10000:
            raise ValueError("笔记请使用不超过一万字的文本")
        s["note"] = value
        _event(s, "note", text=value)
        return {"saved_chars": len(value)}
    if op == "play":
        return _play(s, a)
    if op == "discard":
        match, number = _active(s)
        table = _table(s, match, number)
        card = a.get("card")
        if not any(c["id"] == card for c in table["cards"]):
            raise ValueError("请选择当前手牌中的一个牌号")
        _event(s, "discard", match=match, hand=number, card=card)
        return {"table": _table(s, match, number)}
    if op == "reward":
        choice = a.get("choice")
        if choice not in ("red5", "gold7", "coins"):
            raise ValueError("奖励可选 red5、gold7 或 coins")
        s["reward"] = choice
        if choice == "coins":
            s["cash"] += 2
        else:
            s["bench"] = choice
        _event(s, "reward", choice=choice)
        return {"received": choice, "cash": s["cash"]}
    if op == "reserve":
        choice = a.get("choice")
        if choice not in ("pair_once", "flush_once", "tonic", "none"):
            raise ValueError("预订项可选 pair_once、flush_once、tonic 或 none")
        s["order"] = choice
        _event(s, "reserve", choice=choice)
        return {"order": choice}
    if op == "claim":
        order = s["order"]
        if order == "tonic":
            s["tonics"] += 1
        else:
            s["gears"].append(order)
        s["claimed"] = True
        _event(s, "claim", choice=order)
        return {"received": order}
    if op == "buy":
        gear = a.get("gear")
        if gear not in ("pair_repeat", "flush_repeat") or gear in s["gears"]:
            raise ValueError("请选择尚未购置的一件私人商店持续装")
        s["cash"] -= 4
        s["gears"].append(gear)
        _event(s, "buy", gear=gear, price=4, balance_after=s["cash"])
        return {"received": gear, "cash": s["cash"]}
    if op == "draft":
        seat, gear = a.get("seat"), a.get("gear")
        if seat not in ("standard", "private") or not isinstance(gear, str) or gear not in GEAR:
            raise ValueError("seat 可选 standard、private；gear 须是器材表中的代号")
        if seat == "private" and gear != "none" and gear not in s["gears"]:
            raise ValueError("私人席位只能登记库存中的装备")
        s["draft"][seat] = gear
        _event(s, "draft", seat=seat, gear=gear)
        return {"drafts": s["draft"].copy(), "locked": False}
    if op == "lock":
        s["locked"] = s["draft"].copy()
        _event(s, "lock", **s["locked"])
        return {"entries": s["locked"].copy(), "locked": True}
    if op != "pay":
        raise ValueError("未定义的赛事动作")
    before = s["cash"]
    s["cash"] -= 2
    s["paid"] = True
    _event(s, "pay", amount=2, balance_before=before, balance_after=s["cash"])
    return {"paid": 2, "cash": s["cash"]}


def act(s, action):
    """Reject malformed or out-of-phase actions without changing game state."""
    if not isinstance(action, dict) or not isinstance(action.get("op"), str):
        return {"ok": False, "error": "请传入含 op 的动作对象；查看现场获取可用动作"}
    op = action["op"]
    if op not in _commands(s):
        return {"ok": False, "error": "当前不能执行该动作，请查看现场与可用动作"}
    permitted = set(COMMANDS[op][0])
    if op == "play":
        permitted.add("tonic")
    if action.keys() - permitted:
        return {"ok": False, "error": "含未定义参数，请按动作示例提交"}
    try:
        return {"ok": True, **_apply(s, action)}
    except ValueError as error:
        return {"ok": False, "error": str(error)}
