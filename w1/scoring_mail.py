"""Verify sandbox mailbox transactions, the exact transmitted bytes, and archive receipts."""
from collections import Counter
import hashlib
import json
import re

from .scoring_oracle import PAY, SUMMARY
from .scoring_tables import InvalidArtifact, MAX_BYTES, Table


ROUTES = {
    "finance@office.test": ("out/pay.csv", None),
    "jia@office.test": ("out/jia.csv", "甲"),
    "yi@office.test": ("out/yi.csv", "乙"),
}


def mail_events(run):
    events, anomalies = [], []
    for entry in sorted((run / "mail").glob("*/*")):
        if entry.name.startswith(".stage-"):
            anomalies.append(f"incomplete mail transaction {entry.parent.name}/{entry.name}")
            continue
        event_path = entry / "event.json"
        try:
            if not event_path.is_file() or event_path.stat().st_size > 8192:
                raise ValueError("missing or invalid envelope")
            e = json.loads(event_path.read_bytes())
            if (not isinstance(e, dict) or e.get("receipt") != entry.name or e.get("turn") != int(entry.parent.name)
                or e.get("action") not in {"draft", "deliver"}
                or any(not isinstance(e.get(k), str) for k in ("attachment", "subject", "recipient"))):
                raise ValueError("invalid envelope")
            events.append((e, entry / "payload"))
            if not (entry / "payload").is_file():
                anomalies.append(f"missing journal payload {entry.name}")
        except (OSError, ValueError, TypeError) as exc:
            anomalies.append(f"journal {entry.parent.name}/{entry.name}: {str(exc)[:120]}")
    return events, anomalies


def digest(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise InvalidArtifact("missing or oversized archive")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_mail(run, final, oracle):
    events, anomalies = mail_events(run)
    expected_addresses = Counter({k: 1 for k in ROUTES})
    pay = Table(final / "pay.csv")
    try:
        rows = pay.project(PAY.split())
        got_keys = [(r["project"], r["employee"]) for r in rows]
        valid = (len(set(got_keys)) == len(got_keys) and set(got_keys) == set(oracle["hours"])
                 and all(r["hours"] > 0 and r["bonus"] >= 0 for r in rows))
    except InvalidArtifact:
        rows, valid = [], False
    if valid:
        valid = all(sum(r["bonus"] for r in rows if r["project"] == p) == pool
                    for p, pool in oracle["pools"].items())
    expected = {}
    for address, (filename, project) in ROUTES.items():
        if project is None:
            expected[address] = rows, PAY
        else:
            team = [r for r in rows if r["project"] == project]
            expected[address] = ([dict(project=project, period="2025-07", hours=sum(r["hours"] for r in team),
                                       bonus=sum(r["bonus"] for r in team))], SUMMARY)

    actions = {action: [(e, p) for e, p in events if e["action"] == action]
               for action in ("draft", "deliver")}
    evidence = []
    for action, authorized_turn, weight in (("draft", 8, 2), ("deliver", 9, 2)):
        selected = actions[action]
        counts = Counter(e["recipient"] for e, _ in selected)
        ok = counts == expected_addresses and all(e["turn"] == authorized_turn for e, _ in selected)
        evidence.append((weight, (ok, f"{action} journal: {sorted((e['turn'], e['recipient']) for e, _ in selected)}")))
    for address, (attachment, project) in ROUTES.items():
        reasons = []
        subjects = []
        for_stage = Table(run / "snapshots/7/pay.csv")
        if not for_stage.matches(rows, PAY)[0]:
            reasons.append("filed payroll differs from R7")
        for action, turn in (("draft", 8), ("deliver", 9)):
            matches = [(e, p) for e, p in actions[action] if e["recipient"] == address and e["turn"] == turn]
            if len(matches) != 1:
                reasons.append(f"{action} has {len(matches)} matching events")
                continue
            e, path = matches[0]
            subjects.append(e["subject"])
            if not e["subject"].strip():
                reasons.append(f"{action} empty subject")
            if e["attachment"] != attachment:
                reasons.append(f"{action} wrong attachment name")
            if project and (re.search(r"(?i)E[0-9]{2,}", e["subject"])
                            or any(p in e["subject"] for p in set(oracle["pools"]) - {project})):
                reasons.append(f"{action} subject discloses other payroll information")
            data, fields = expected[address]
            ok, why = Table(path).matches(data, fields, exact_headers=True)
            if not (valid and ok):
                reasons.append(f"{action} payload: {why}" if valid else "invalid filed payroll")
        if len(set(subjects)) > 1:
            reasons.append("delivery subject differs from draft")
        evidence.append((1, (not reasons, f"{address}: " + ("; ".join(reasons) or "draft & delivery payloads match"))))

    sent = [e for e, p in actions["deliver"]]
    # A candidate's receipt index cannot substitute for a missing or extra journal entry.
    receipts = Table(final / "receipts.csv")
    ok, why = receipts.matches(sent, "recipient receipt attachment")
    count_ok = Counter(e["recipient"] for e in sent) == expected_addresses and all(e["turn"] == 9 for e in sent)
    archive = [(2, (ok and count_ok, "receipts.csv vs actual deliveries: " + why))]
    bytes_ok = count_ok
    for event, payload in actions["deliver"]:
        address = event["recipient"]
        if address not in ROUTES or event["attachment"] != ROUTES[address][0]:
            bytes_ok = False
            continue
        try:
            if digest(final / ROUTES[address][0].split("/")[1]) != digest(payload):
                bytes_ok = False
        except (OSError, ValueError):
            bytes_ok = False
    archive.append((1, (bytes_ok, "SHA-256 of all three archived files compared with actual delivered bytes")))
    return evidence, archive, anomalies
