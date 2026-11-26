"""Extract failed jobs from the independent worker log."""
import json
import sys
from pathlib import Path


def main(source, destination):
    jobs = set()
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if entry["result"] == "failed":
                jobs.add(entry["job_id"])
    destination.write_text("".join(f"{job}\n" for job in sorted(jobs)), encoding="utf-8")


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
