"""Run the public continuous release desk through Claude Code and DeepSeek Flash."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from tasks.w1.claude import run_claude
from tasks.w1.gateway import Gateway, MODEL, URL
from tasks.w1.runstate import prepare, freeze
from .scenario import init, release, ROUNDS
from .office import ALLOWED, invoke

CONTEXT = (
    "你是区域售后服务运营专员。通过 office 的四个业务工具在共享盘和模拟邮箱工作。"
    "请使用 shell 读 input、inbox，写 out、notes、scratch；工位跨轮持久，Docker内可用 python3/openpyxl。"
    "请先读 input/办公室/发布规程.txt。用户只看 out 中的交接表、手册和真实邮件。每轮简报完成及待办。"
)


def save(path, value):
    stage = path.with_suffix(".tmp")
    stage.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    stage.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def boundary(run, image):
    result = invoke(
        run,
        1,
        image,
        "shell",
        {
            "command": """python3 - <<'PYCODE'
import os,socket
from pathlib import Path
from openpyxl import load_workbook
assert Path.cwd()==Path('/office') and Path('input/办公室/发布规程.txt').is_file()
assert not Path('../trace').exists() and not Path('mail').exists()
assert not any(x in os.environ for x in ('ARK_API_KEY','ANTHROPIC_API_KEY'))
for action in [lambda: Path('input/.probe').write_text('bad'),lambda:socket.create_connection(('1.1.1.1',443),1)]:
 try: action()
 except OSError: pass
 else: raise RuntimeError('unexpected access')
assert '交割' in load_workbook('out/交接.xlsx',read_only=True).sheetnames
p=Path('scratch/.probe');p.write_text('ready');assert p.read_text()=='ready';p.unlink()
print('workspace ready')
PYCODE"""
        },
    )
    if result["status"] or "workspace ready" not in result["output"]:
        raise RuntimeError("Docker isolation or mount failure: " + str(result))
    return result


QUOTA_CONTEXT = "你是四站服务运营专员。用 office 工具读 input/办公室/发布规程.txt，按业务日处理 inbox。共享盘可用 Python/openpyxl/Calc，out/notes/scratch 跨轮保留。简报只写本轮结果与未结事项。"


def run(dest, edition="4"):
    revised = str(edition) == "3.1"
    edition = 3 if revised else int(edition)
    if edition not in (1, 2, 3, 4):
        raise ValueError("未知 W4 题面")
    key = os.environ["ARK_API_KEY"]
    image = subprocess.check_output(
        ["docker", "image", "inspect", "longworkmem-release:1", "-f", "{{.Id}}"],
        text=True,
    ).strip()
    work = prepare(dest)
    if edition == 4:
        from .quota import world

        world.initialize(work)
    else:
        init(work)
    if edition in (2, 3):
        from . import annex

        annex.initialize(work)
    if edition == 3:
        from . import night

        night.initialize(work)
        if revised:
            with (work / "input/办公室/发布规程.txt").open("a") as f:
                f.write(night.FIELD_GUIDE)
    sid = str(uuid.uuid4())
    meta = dict(
        protocol=f"w4-release-v{edition}",
        seed=17217,
        variant="A",
        model=MODEL,
        session=sid,
        harness="Claude Code",
        cli=subprocess.check_output(["claude", "--version"], text=True).strip(),
        image=image,
        git=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True
        ).strip(),
        reasoning="provider-default",
        limit=None,
        start=now(),
        status="running",
        turns=[],
    )
    if revised:
        meta["release_revision"] = "3.1"
    save(dest / "manifest.json", meta)
    try:
        meta["isolation"] = boundary(dest, image)
        with (
            tempfile.TemporaryDirectory(prefix="desk-client-") as tmp,
            Gateway(
                key,
                dest,
                model=MODEL,
                url=URL,
                allowed=ALLOWED,
                timeout=600,
                private_markers=(
                    "tasks/w4/grade",
                    "W4_NIGHT_GRADER_3a9",
                    "W4_PRIVATE_ORACLE_7cf2",
                    "W4_QUOTA_PRIVATE_A79",
                    "w4-implementation",
                ),
            ) as gw,
        ):
            client = Path(tmp)
            (client / "desk").mkdir()
            for t in ROUNDS:
                prompt = world.release(work, t) if edition == 4 else release(work, t)
                if edition in (2, 3):
                    prompt += annex.release(work, t)
                if edition == 3:
                    prompt += night.release(work, t)
                if edition >= 2:
                    from .visibility import await_inbox

                    meta.setdefault("inbox_visibility", []).append(
                        await_inbox(dest, t, image)
                    )
                (dest / "trace" / f"prompt-{t}.txt").write_text(prompt)
                cfg = {
                    "mcpServers": {
                        "office": {
                            "command": sys.executable,
                            "args": ["-m", "tasks.w4.office", str(dest), str(t), image],
                            "env": {
                                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                                "DOCKER_HOST": os.environ.get(
                                    "DOCKER_HOST", "unix:///var/run/docker.sock"
                                ),
                            },
                        }
                    }
                }
                calls = run_claude(
                    dest,
                    t,
                    gw,
                    sid,
                    prompt,
                    client,
                    config=cfg,
                    context=QUOTA_CONTEXT if edition == 4 else CONTEXT,
                    allowed=ALLOWED,
                    first_session=t == 1,
                )
                freeze(dest, t, rounds=ROUNDS)
                meta["turns"].append({"turn": t, "calls": calls, "end": now()})
                save(dest / "manifest.json", meta)
                print(f"R{t}/12 {calls} requests", flush=True)
        meta["status"] = "complete"
    except BaseException:
        meta["status"] = "error"
        raise
    finally:
        meta["end"] = now()
        save(dest / "manifest.json", meta)
    from .grade import grade

    save(dest / "grade.json", grade(dest))
    if edition == 2:
        from .outcome_score import score

        save(dest / "grade-outcomes-1.json", score(dest))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest", type=Path)
    p.add_argument("--edition", choices=("1", "2", "3", "3.1", "4"), default="4")
    p.add_argument("--replay", action="store_true")
    a = p.parse_args()
    dest = a.dest.resolve()
    if a.replay:
        from .grade import grade

        print(json.dumps(grade(dest), ensure_ascii=False, indent=2))
    else:
        run(dest, a.edition)
