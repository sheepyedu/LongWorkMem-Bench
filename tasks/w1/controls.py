"""Local hashing and JSON helpers for advanced short controls."""
import hashlib
import json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_digest(seed):
    checksum = hashlib.sha256()
    for path in sorted(p for p in seed.rglob("*") if p.is_file()):
        checksum.update(path.relative_to(seed).as_posix().encode() + b"\0")
        checksum.update(bytes.fromhex(digest(path)))
    return checksum.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
