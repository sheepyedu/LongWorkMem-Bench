"""JSONL and message-content readers for native trajectory audits."""
import json


def enc(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def lines(p):
    if not p.exists():
        return []
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]


def result_text(blocks):
    if isinstance(blocks, str):
        return blocks
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
