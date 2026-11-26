"""Private scoring of frozen S1 game ledgers. Only the host runs this module."""
import argparse
from collections import Counter
from copy import deepcopy
from itertools import product
import json
from pathlib import Path


VERSION = "s1-grade/1.0"
GEAR = {"pair_repeat", "pair_once", "flush_repeat", "flush_once", "none"}
ITEMS = (
    ("main1", 2, "early", 7),
    ("main2", 3, "early", 8),
    ("invite1", 4, "invitation", 7),
    ("invite2", 4, "invitation", 8),
    ("return_first", 5, "recovery", 10),
    ("return", 5, "recovery", 5),
    ("standard", 7, "standard", 30),
    ("free1", 8, "finals", 10),
    ("free2", 8, "finals", 10),
    ("payment", 8, "finals", 5),
)


class InvalidEvidence(ValueError):
    """Host evidence is inconsistent or cannot be decoded."""


def require(condition, reason):
    if not condition:
        raise InvalidEvidence(reason)


def read_json(path):
    def unique(pairs):
        data = dict(pairs)
        require(len(data) == len(pairs), "duplicate JSON key")
        return data

    def bad_number(value):
        raise InvalidEvidence(f"invalid JSON number {value}")

    try:
        with path.open(encoding="utf-8-sig") as src:
            return json.load(src, object_pairs_hook=unique, parse_constant=bad_number)
    except (OSError, ValueError, RecursionError) as error:
        raise InvalidEvidence(f"{path.name}: {error}") from error


def checked_history(state, variant, seed, turn, previous):
    require(isinstance(state, dict), "snapshot is not an object")
    require(state.get("variant") == variant and type(state.get("seed")) is int
            and state["seed"] == seed, "snapshot variant or seed mismatch")
    require(type(state.get("turn")) is int and state["turn"] == turn, "snapshot turn mismatch")
    events = state.get("events")
    require(isinstance(events, list), "missing event ledger")
    require(events[:len(previous)] == previous, "previous frozen events changed")
    last = 1
    for event in events:
        require(isinstance(event, dict) and isinstance(event.get("kind"), str),
                "malformed event")
        n = event.get("turn")
        require(type(n) is int and last <= n <= turn, "invalid event turn/order")
        last = n
    return events


def check_cards(cards):
    require(isinstance(cards, list) and cards, "empty or malformed cards")
    for card in cards:
        require(isinstance(card, dict) and isinstance(card.get("id"), str)
                and card["id"] and type(card.get("rank")) is int
                and isinstance(card.get("suit"), str) and card["suit"], "invalid card")
    require(len({card["id"] for card in cards}) == len(cards), "duplicate card")


def legal_patterns(cards):
    check_cards(cards)
    ranks = Counter(card["rank"] for card in cards)
    suits = Counter(card["suit"] for card in cards)
    patterns = ["single"]
    if max(ranks.values()) >= 2:
        patterns.append("pair")
    if max(suits.values()) >= 3:
        patterns.append("flush")
    return patterns


def final_points(pattern, gear, blocked, triggered):
    points = 1 if pattern == "single" else 4
    if gear == "none":
        return points, triggered
    family, mode = gear.split("_")
    if family == pattern and family != blocked:
        if mode == "repeat":
            points += 4
        elif not triggered:
            points += 7
            triggered = True
    return points, triggered


def standard_maximum(hands, equipment, variant):
    """Search attainable sequences using the actual two frozen rental hands."""
    require(isinstance(equipment, str) and equipment in GEAR, "unknown rental equipment")
    require(variant in ("A", "B"), "unknown variant")
    require(isinstance(hands, list) and len(hands) == 2, "expected two rental hands")
    best = 0
    for plays in product(*(legal_patterns(hand) for hand in hands)):
        total, triggered = 0, False
        for pattern in plays:
            value, triggered = final_points(pattern, equipment,
                                            "pair" if variant == "A" else "flush", triggered)
            total += value
        best = max(best, total)
    return best


def lock_event(events):
    locks = [e for e in events if e["kind"] == "lock"]
    require(len(locks) <= 1, "duplicate lock")
    if not locks:
        return None
    lock = locks[0]
    require(lock["turn"] == 7, "registration outside registration round")
    for field in ("standard", "private"):
        require(isinstance(lock.get(field), str) and lock[field] in GEAR,
                f"unknown {field} equipment")
    return lock


def standard_result(state, variant):
    lock = lock_event(state["events"])
    if lock is None:
        return False, "no confirmed registration"
    result = standard_maximum(state.get("standard_hands"), lock["standard"], variant)
    return result >= 15, f"locked {lock['standard']}, attainable {result}/15"


def grade_standard(state, variant):
    """Short-control readout, scored independently of the natural eight-turn run."""
    try:
        require(variant in ("A", "B"), "invalid variant")
        require(isinstance(state, dict) and type(state.get("seed")) is int, "missing seed")
        checked_history(state, variant, state["seed"], 7, [])
        passed, reason = standard_result(state, variant)
        return {"valid": True, "points": 30 if passed else 0, "max": 30, "reason": reason}
    except InvalidEvidence as error:
        return {"valid": False, "points": 0, "max": 30, "reason": str(error)}


MATCHES = {2: ("main1",), 3: ("main2",), 4: ("invite1", "invite2"),
           5: ("return",), 8: ("free1", "free2")}


def score_hands(state, turn, match, *, first_only=False):
    events = state["events"]
    plays = [event for event in events if event["turn"] == turn and event["kind"] == "play"]
    require(all(event.get("match") in MATCHES[turn] for event in plays),
            "unexpected match for stage")
    hand_count = 1 if turn == 4 else 2
    schedule = [(name, i) for name in MATCHES[turn] for i in range(1, hand_count + 1)]
    actual = [(event["match"], event.get("hand")) for event in plays]
    require(all(type(event.get("hand")) is int for event in plays)
            and actual == schedule[:len(plays)], "duplicate, missing or out-of-order play")
    selected = [event for event in plays if event["match"] == match]
    expected = 1 if first_only else hand_count
    if first_only:
        selected = selected[:1]
    if len(selected) < expected:
        return False, f"played {len(selected)}/{expected} required hands"

    triggered, total = False, 0
    for event in selected:
        available, cards, pattern = event.get("available"), event.get("cards"), event.get("pattern")
        check_cards(available)
        check_cards(cards)
        require(all(card in available for card in cards), "selected undealt card")
        require(isinstance(pattern, str) and pattern in legal_patterns(cards), "invalid hand pattern")
        require(len(cards) == {"single": 1, "pair": 2, "flush": 3}[pattern],
                "incorrect selection size")
        base = 1 if pattern == "single" else 4
        station = gear_bonus = tonic_bonus = 0
        tonic = event.get("tonic")
        require(type(tonic) is bool, "malformed tonic flag")
        if turn == 8:
            registration = lock_event(events)
            gear = registration["private"] if registration else "none"
            require(event.get("gear") == gear,
                    "private equipment differs from registration")
            score, triggered = final_points(pattern, gear,
                                            "pair" if state["variant"] == "A" else "flush", triggered)
            gear_bonus = score - base
            tonic_bonus = 7 if tonic else 0
        else:
            require(not tonic, "tonic outside private final")
            rewarded = "flush" if turn == 4 else "pair"
            station = 4 if pattern == rewarded else 0
        points = base + station + gear_bonus + tonic_bonus
        for key, value in (("base", base), ("station_bonus", station), ("gear_bonus", gear_bonus),
                           ("tonic_bonus", tonic_bonus), ("points", points)):
            require(type(event.get(key)) is int and event[key] == value,
                    f"{match} hand {event['hand']} inconsistent {key}")
        total += points
    target = 8 if first_only or turn == 4 else 15 if turn == 8 else 12
    if not first_only:
        results = [e for e in events if e["turn"] == turn and e["kind"] == "result"
                   and e.get("match") == match]
        require(len(results) == 1 and type(results[0].get("points")) is int
                and results[0]["points"] == total and results[0].get("qualified") is (total >= target),
                f"inconsistent {match} settlement")
    return total >= target, f"{len(selected)} played, {total}/{target}"


def payment_result(state):
    events = state["events"]
    receipts = [i for i, event in enumerate(events) if event["kind"] == "pay"]
    if not receipts:
        return False, "no payment receipt"
    require(len(receipts) == 1, "duplicate payment receipt")
    i = receipts[0]
    receipt = events[i]
    require(receipt["turn"] == 8 and type(receipt.get("amount")) is int
            and receipt["amount"] == 2, "incorrect payment amount/stage")
    before, after = receipt.get("balance_before"), receipt.get("balance_after")
    require(type(before) is int and type(after) is int and before - 2 == after and after >= 0,
            "invalid payment balances")
    played = [(e.get("match"), e.get("hand")) for e in events[:i]
              if e["turn"] == 8 and e["kind"] == "play"]
    require(played == [("free1", 1), ("free1", 2), ("free2", 1), ("free2", 2)],
            "payment before both finals completed")
    return True, f"paid 2 after both completed, {before} -> {after}"


def replay_calls(run, simulated, turn):
    from .game import act, observe
    path = run / "trace" / f"tools-{turn}.jsonl"
    with path.open(encoding="utf-8-sig") as stream:
        for n, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            require(isinstance(row, dict) and type(row.get("turn")) is int
                    and row["turn"] == turn, f"invalid tool record at line {n}")
            result = row.get("result")
            require(isinstance(result, dict), f"missing tool result at line {n}")
            if row.get("tool") == "observe" and row.get("args") == {}:
                require(observe(simulated) == result, f"observation differs at line {n}")
                continue
            if result.get("ok") is False:
                continue
            arguments = row.get("args")
            require(row.get("tool") == "act" and result.get("ok") is True and
                    isinstance(arguments, dict) and isinstance(arguments.get("action"), dict),
                    f"invalid accepted action at line {n}")
            outcome = act(simulated, arguments["action"])
            require(outcome == result, f"recorded receipt differs from replay at line {n}")


def replay_turn(run, previous, state, variant, seed, turn):
    """Cross-check secured snapshots against the independently recorded tool actions."""
    from .game import new_game, open_turn

    simulated = deepcopy(previous) if previous else new_game(variant, seed)
    for n in range(simulated["turn"] + 1, turn + 1):
        open_turn(simulated, n)
        replay_calls(run, simulated, n)
    require(simulated == state, "replayed game differs from frozen snapshot")


def grade_control(run, manifest):
    from .game import new_game, open_turn

    issues = []
    variant, seed = manifest["variant"], manifest["seed"]
    if manifest.get("status") not in ("complete", "budget_exhausted", "early_stop"):
        issues.append(f"run status {manifest.get('status')!r}")
    try:
        previous = new_game(variant, seed)
        for turn in range(1, 7):
            open_turn(previous, turn)
        state = read_json(run / "snapshots/7.json")
        checked_history(state, variant, seed, 7, previous["events"])
        replay_turn(run, previous, state, variant, seed, 7)
        passed, reason = standard_result(state, variant)
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        reason = str(error)
        issues.append(reason)
        passed = False
    item = {"id": "standard", "turn": 7, "group": "standard", "max": 30,
            "points": 30 if passed else 0, "reason": reason}
    return {"scorer": VERSION, "variant": variant, "seed": seed, "mode": manifest["mode"],
            "valid": not issues, "total": item["points"], "max_score": 30,
            "strict_pass": passed and not issues, "items": [item], "infrastructure_anomalies": issues}


def grade(run):
    run = Path(run)
    anomalies, snapshots = [], {}
    manifest = {}
    try:
        manifest = read_json(run / "manifest.json")
        require(isinstance(manifest, dict) and manifest.get("variant") in ("A", "B")
                and type(manifest.get("seed")) is int, "invalid run manifest")
    except InvalidEvidence as error:
        anomalies.append(str(error))
        manifest = {}
    variant, seed = manifest.get("variant"), manifest.get("seed")
    status = manifest.get("status")
    if manifest.get("mode") in ("current", "reminder"):
        return grade_control(run, manifest)
    if status not in ("complete", "budget_exhausted", "early_stop"):
        anomalies.append(f"run status {status!r}")
    previous = None
    for turn in range(1, 9):
        path = run / "snapshots" / f"{turn}.json"
        if not manifest:
            break
        if not path.exists() and status in ("budget_exhausted", "early_stop"):
            if any((run / "snapshots" / f"{n}.json").exists() for n in range(turn + 1, 9)):
                anomalies.append(f"R{turn}: gap in frozen stages")
            continue
        try:
            state = read_json(path)
            checked_history(state, variant, seed, turn, previous["events"] if previous else [])
            replay_turn(run, previous, state, variant, seed, turn)
            snapshots[turn], previous = state, state
        except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
            anomalies.append(f"R{turn}: {error}")

    items = []
    for name, turn, group, weight in ITEMS:
        state = snapshots.get(turn)
        passed, reason = False, "no usable frozen stage"
        if state is not None:
            try:
                if name == "standard":
                    passed, reason = standard_result(state, variant)
                elif name == "payment":
                    passed, reason = payment_result(state)
                elif name == "return_first":
                    passed, reason = score_hands(state, turn, "return", first_only=True)
                else:
                    passed, reason = score_hands(state, turn, name)
            except InvalidEvidence as error:
                reason = str(error)
                anomalies.append(f"{name}: {reason}")
        items.append({"id": name, "turn": turn, "group": group, "max": weight,
                      "points": weight if passed else 0, "reason": reason})
    total = sum(i["points"] for i in items)
    return {"scorer": VERSION, "variant": variant, "seed": seed, "valid": not anomalies,
            "total": total, "max_score": 100, "strict_pass": total == 100 and not anomalies,
            "items": items, "infrastructure_anomalies": anomalies}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(grade(args.run), indent=2, ensure_ascii=False))
