"""Run paired, fresh-session July payroll diagnostics from the reference June/July handoff."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import uuid

from .gateway import Gateway, MODEL
from .grade import grade, selected
from .pilot import blinded_office, claude_turn, isolation_check, source_hashes
from .reference import solve_turn
from .runstate import freeze
from .scoring_mail import mail_events
from .scoring_oracle import PAY, expected
from .scoring_tables import Table
from .world import release


ARMS = ("current", "reminder")
LIMIT = 50


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_digest(seed):
    checksum = hashlib.sha256()
    for path in sorted(p for p in seed.rglob("*") if p.is_file()):
        checksum.update(path.relative_to(seed).as_posix().encode() + b"\0")
        checksum.update(bytes.fromhex(digest(path)))
    return checksum.hexdigest()


def make_seed(path, variant):
    """Preserve the R6 handoff outside the office. No assistant chat or working notes."""
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    for turn in range(1, 7):
        release(path, turn, variant)
        solve_turn(path, turn)
    for file in path.rglob("*"):
        if file.is_file():
            file.chmod(0o444)
    return path


def prepare_short(work, seed, variant, arm):
    if arm not in ARMS:
        raise ValueError(f"Unknown diagnostic arm {arm!r}")
    for directory in ("input", "inbox", "out"):
        shutil.copytree(seed / directory, work / directory, copy_function=shutil.copyfile,
                        dirs_exist_ok=True)
    prompt = release(work, 7, variant)
    if arm == "reminder":
        message = BytesParser(policy=policy.default).parsebytes((work / "inbox/HR-0628.eml").read_bytes())
        approved, = (line for line in message.get_content().splitlines() if line.startswith("批准生效日："))
        prompt += f"\n另附人事部关于 E07 共享支援工时转归的批复原文：“{approved}”。"
    return prompt


def score_short(run, variant):
    """Project the unchanged formal rubric onto the one requested payroll checkpoint."""
    full = grade(run, variant)
    items = {name: item for name, item in full["items"].items() if name.startswith("CP4.")}
    hr_passed, why = selected(Table(run / "snapshots/7/pay.csv"), expected(variant)["pay"], PAY,
                              lambda row: row["employee"] == "E07")
    journal, anomalies = mail_events(run)
    mail = {"unsolicited_deliveries": [e for e, _ in journal if e["action"] == "deliver"],
            "unsolicited_drafts": [e for e, _ in journal if e["action"] == "draft"],
            "journal_anomalies": anomalies}
    return dict(mail_side_effects=mail, variant=variant, turn=7, scorer_version=full["scorer_version"], items=items,
                total=sum(item["earned"] for item in items.values()),
                max=sum(item["max"] for item in items.values()), hr_passed=hr_passed, hr_reason=why)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def play_short(run, seed, variant, arm, backend, key):
    run.parent.mkdir(parents=True, exist_ok=True)
    with blinded_office(run, backend) as work:
        session = str(uuid.uuid4())
        manifest = dict(
            variant=variant, arm=arm, backend=backend, session=session, model=MODEL,
            upstream="Ark Chat Completions, default thinking", limit=LIMIT,
            claude=subprocess.check_output(["claude", "--version"], text=True).strip(),
            git=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                        cwd=Path(__file__).resolve().parent).strip(),
            platform=platform.platform(), python=platform.python_version(), file_hashes=source_hashes(),
            seed="reference-authored R6 office; previous agent messages and notes absent",
            seed_path=os.path.relpath(seed, run), seed_sha256=seed_digest(seed),
            start=datetime.now(timezone.utc).isoformat(), turns=[], status="running",
        )
        state = run / "manifest.json"
        write_json(state, manifest)
        try:
            prompt = prepare_short(work, seed, variant, arm)
            prompt_path = run / "trace/prompt-7.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            manifest["prompt_sha256"] = digest(prompt_path)
            manifest["isolation"] = isolation_check(work, backend)
            write_json(state, manifest)
            with tempfile.TemporaryDirectory(prefix="office-client-") as tmp, Gateway(key, run, LIMIT) as gateway:
                client = Path(tmp)
                (client / "desk").mkdir()
                calls = claude_turn(run, 7, backend, gateway, session, prompt, client, first_session=True)
            freeze(run, 7)
            manifest["turns"].append(dict(turn=7, upstream_calls=calls))
            result = score_short(run, variant)
            write_json(run / "grade-cp4.json", result)
            manifest["status"] = "complete"
            print(f"{arm}/{variant}: CP4 {result['total']}/{result['max']} ({calls} upstream calls)", flush=True)
            return result
        except Exception as exc:
            manifest.update(status="error", error=str(exc))
            raise
        finally:
            manifest["end"] = datetime.now(timezone.utc).isoformat()
            write_json(state, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--backend", choices=["docker", "seatbelt"], default="docker")
    args = parser.parse_args()
    dest = args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    seeds = {variant: make_seed(dest / "seeds" / variant, variant) for variant in ("A", "B")}
    credential = os.environ.get("ARK_API_KEY") or getpass.getpass("Ark credential (hidden): ")
    with ThreadPoolExecutor(max_workers=4) as pool:
        sessions = [pool.submit(play_short, dest / arm / variant, seed, variant, arm, args.backend, credential)
                    for arm in ARMS for variant, seed in seeds.items()]
        for session in sessions:
            session.result()


if __name__ == "__main__":
    main()
