"""Run a blinded nine-turn Claude Code trajectory against Ark."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid

from .claude import run_claude
from .gateway import Gateway, MODEL, OFFICE_TOOLS
from .office import IMAGE, shell
from .runstate import ROUNDS, freeze, prepare
from .world import release

CONTEXT = ("你是企业财务运营助理。通过 office 的 shell 操作本次业务共享盘，通过 draft 和 deliver 处理内部邮件。"
           "使用 python3 和 openpyxl 读写文件；共享盘中的 input、inbox 可读，out、notes、scratch 可写。"
           "当前业务材料和对话决定交付内容。完成本次委托时向用户简要说明实际完成情况和待处理事项。")


@contextmanager
def blinded_office(run, backend):
    work = prepare(run)
    if backend == "docker":
        yield work
        return
    # Keep host labels and the repository name out of pwd, even across resumes.
    with tempfile.TemporaryDirectory(prefix="office-") as tmp:
        anonymous = Path(tmp).resolve() / "department"
        shutil.move(str(work), anonymous)
        work.symlink_to(anonymous, target_is_directory=True)
        try:
            yield work
        finally:
            work.unlink()
            shutil.move(str(anonymous), work)


def docker_image():
    return subprocess.check_output(["docker","image","inspect",IMAGE,"--format","{{.Id}}"],text=True).strip()


def claude_turn(run, turn, backend, gw, session, prompt, client, *, first_session=None):
    office_env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    if backend == "docker":
        if os.environ.get("DOCKER_HOST"):
            office_env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
        office_env["W1_OFFICE_IMAGE_ID"] = docker_image()
    config = {"mcpServers": {"office": {"command": sys.executable,
        "args": ["-m", "w1.office", str(run.resolve()), str(turn), backend],
        "env": office_env}}}
    context = CONTEXT + ("本办公室支持使用 soffice --headless 在副本上实际重算 Excel。" if backend == "docker" else "")
    return run_claude(run, turn, gw, session, prompt, client, config=config, context=context,
                      allowed=OFFICE_TOOLS, first_session=turn == 1 if first_session is None else first_session)


def isolation_check(work, backend):
    private = work.parent / "isolation-marker"
    private.write_text(secrets.token_hex(16))
    public = work / "input" / ".boundary-check"
    public.write_text("public")
    # Both relative and real host paths must be inaccessible, even when known.
    command = """python3 - <<'END'
import pathlib, socket
from openpyxl import Workbook
p=pathlib.Path
assert p('input/.boundary-check').read_text()=='public'
assert 'LongWorkMem' not in str(p.cwd()) and p.cwd().name in ('department','office')
assert not any(x.upper() in ('A','B') for x in p.cwd().parts)
Workbook().save('scratch/probe.xlsx')
for action in [lambda: p('../isolation-marker').read_bytes(),lambda: p(HOST_MARKER).read_bytes(),
               lambda: p(SCORER).read_bytes(), lambda: p('input/.boundary-check').write_text('bad')]:
    try: action()
    except OSError: continue
    raise SystemExit('private file access or input mutation permitted')
try: socket.create_connection(('1.1.1.1',443),timeout=1)
except OSError: pass
else: raise SystemExit('network access permitted')
print('office boundary OK')
END""".replace("HOST_MARKER",repr(str(private.resolve()))).replace("SCORER",repr(str(Path(__file__).parent.resolve()/"grade.py")))
    try:
        result = shell(work, command, backend)
        if result["status"] or "office boundary OK" not in result["output"]:
            raise RuntimeError("Office boundary failed: "+str(result))
        return result
    finally:
        public.unlink(missing_ok=True)
        private.unlink(missing_ok=True)
        (work / "scratch/probe.xlsx").unlink(missing_ok=True)


def source_hashes():
    import hashlib
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(Path(__file__).parent.glob("*.py"))}


def play(run, variant, backend, key, smoke=False, limit=1500):
    with blinded_office(run, backend) as work:
        return execute(run, work, variant, backend, key, smoke, limit)


def execute(run, work, variant, backend, key, smoke, limit):
    session = str(uuid.uuid4())
    manifest = {"variant":variant,"backend":backend,"model":MODEL,"session":session,
                "claude":subprocess.check_output(["claude","--version"],text=True).strip(),
                "git":subprocess.check_output(["git","rev-parse","HEAD"],cwd=Path(__file__).resolve().parent,text=True).strip(),
                "start":datetime.now(timezone.utc).isoformat(),"limit":limit,"upstream":"Ark Chat Completions, default thinking",
                "smoke":smoke,"turns":[], "file_hashes": source_hashes()}
    if backend == "docker":
        manifest["docker_image"] = docker_image()
    state = run / "manifest.json"
    def save():
        state.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    save()
    try:
        manifest["isolation"] = isolation_check(work, backend)
        with tempfile.TemporaryDirectory(prefix="office-client-") as tmp, Gateway(key, run,limit) as gw:
            client = Path(tmp); (client/"desk").mkdir()
            if smoke:
                (work/"input"/"notice").write_text("采购代号 "+secrets.token_hex(4))
            for turn in ([1] if smoke else ROUNDS):
                prompt = ("请用共享盘 shell 读 input/notice 的采购代号，在 out/reply.txt 写入完整原文并告诉我结果。"
                          if smoke else release(work,turn,variant))
                (run/"trace"/f"prompt-{turn}.txt").write_text(prompt)
                n = claude_turn(run,turn,backend,gw,session,prompt,client)
                freeze(run,turn)
                manifest["turns"].append({"turn":turn,"upstream_calls":n})
                save()
                print(f"{variant} turn {turn} complete ({n} upstream calls)",flush=True)
                if smoke and (work/"out/reply.txt").read_text().strip() != (work/"input/notice").read_text().strip():
                    raise RuntimeError("Claude tool round trip did not return the office value")
        manifest["status"]="complete"
    except Exception as exc:
        manifest["status"]="error"; manifest["error"]=str(exc)
        raise
    finally:
        manifest["end"]=datetime.now(timezone.utc).isoformat()
        save()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest",type=Path)
    p.add_argument("--variants",nargs="+",choices=["A","B"],default=["A","B"])
    p.add_argument("--backend",choices=["docker","seatbelt"],default="docker")
    p.add_argument("--smoke",action="store_true")
    p.add_argument("--limit",type=int,default=1500)
    args=p.parse_args()
    if len(set(args.variants))!=len(args.variants):
        p.error("Use each variant at most once per destination")
    dest=args.dest.resolve(); dest.mkdir(parents=True,exist_ok=True)
    key=os.environ.get("ARK_API_KEY") or getpass.getpass("Ark credential (hidden): ")
    with ThreadPoolExecutor(max_workers=len(args.variants)) as pool:
        batch=[pool.submit(play,dest/v,v,args.backend,key,args.smoke,args.limit) for v in args.variants]
        for item in batch:
            item.result()


if __name__ == "__main__":
    main()
