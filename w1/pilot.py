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

from .gateway import Gateway, MODEL, URL
from .office import IMAGE, shell
from .runstate import ROUNDS, freeze, prepare
from .world import release

CONTEXT = ("你是企业财务运营助理。通过 office 的 shell 操作本次业务共享盘，通过 draft 和 deliver 处理内部邮件。"
           "使用 python3 和 openpyxl 读写文件；共享盘中的 input、inbox 可读，out、notes、scratch 可写。"
           "存入 out/ 即完成文件交付。对外分发的邮件按委托拟稿，收到明确发送指示后才投递。"
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


def claude_turn(run, turn, backend, gw, session, prompt, client, *, first_session=None, image_id=None):
    office_env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    if backend == "docker":
        if os.environ.get("DOCKER_HOST"):
            office_env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
        office_env["W1_OFFICE_IMAGE_ID"] = image_id or docker_image()
    config = {"mcpServers": {"office": {"command": sys.executable,
        "args": ["-m", "w1.office", str(run.resolve()), str(turn), backend],
        "env": office_env}}}
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code executable missing")
    env = {"PATH": os.environ["PATH"], "HOME": str(client), "CLAUDE_CONFIG_DIR": str(client/"config"),
           "ANTHROPIC_BASE_URL": gw.base, "ANTHROPIC_API_KEY": gw.token,
           "ANTHROPIC_MODEL": gw.model, "ANTHROPIC_SMALL_FAST_MODEL": gw.model,
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1",
           "DISABLE_ERROR_REPORTING":"1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY":"1",
           "CLAUDE_CODE_ATTRIBUTION_HEADER":"0", "ENABLE_TOOL_SEARCH":"false",
           "NO_PROXY":"127.0.0.1,localhost", "LANG": "en_US.UTF-8"}
    if first_session is None:
        first_session = turn == 1
    argv = [exe, "-p", "--bare", "--model", gw.model, "--strict-mcp-config", "--mcp-config", json.dumps(config),
            "--settings", "{}", "--setting-sources", "", "--tools", "", "--permission-mode", "dontAsk",
            "--allowedTools", "mcp__office__shell,mcp__office__draft,mcp__office__deliver",
            "--disable-slash-commands", "--system-prompt", CONTEXT + ("本办公室支持使用 soffice --headless 在副本上实际重算 Excel。" if backend == "docker" else ""), "--output-format", "stream-json", "--verbose",
            "--session-id" if first_session else "--resume", session]
    gw.turn = turn
    start = gw.count
    stdout = run / "trace" / f"turn-{turn}.jsonl"
    with stdout.open("x") as out, (run/"trace"/f"turn-{turn}.stderr").open("x") as err:
        proc = subprocess.run(argv, cwd=client/"desk", env=env, input=prompt, text=True, stdout=out, stderr=err, timeout=1800)
    result = None
    with stdout.open() as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("type") == "result":
                result = event
    if proc.returncode or not result or result.get("is_error") or gw.count == start:
        message = str(result.get("result",""))[:550] if result else "missing result"
        raise RuntimeError(f"turn {turn} harness failed (exit {proc.returncode}, {gw.count-start} upstream calls): {message}")
    return gw.count-start


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


def play(run, variant, backend, key, smoke=False, limit=1500, *, model=MODEL, url=URL, level=0, seed=0):
    with blinded_office(run, backend) as work:
        return execute(run, work, variant, backend, key, smoke, limit, model, url, level, seed)


def execute(run, work, variant, backend, key, smoke, limit, model=MODEL, url=URL, level=0, seed=0):
    session = str(uuid.uuid4())
    manifest = {"variant":variant,"backend":backend,"model":model,"session":session,
                "claude":subprocess.check_output(["claude","--version"],text=True).strip(),
                "git":subprocess.check_output(["git","rev-parse","HEAD"],cwd=Path(__file__).resolve().parent,text=True).strip(),
                "start":datetime.now(timezone.utc).isoformat(),"limit":limit,"upstream":url,
                "smoke":smoke,"turns":[], "file_hashes": source_hashes()}
    if level:
        from . import advanced
        manifest.update(task="W1-advanced", level=level, seed=seed)
    if backend == "docker":
        manifest["docker_image"] = docker_image()
    state = run / "manifest.json"
    def save():
        state.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    save()
    try:
        manifest["isolation"] = isolation_check(work, backend)
        with tempfile.TemporaryDirectory(prefix="office-client-") as tmp, Gateway(key, run,limit,model=model,url=url) as gw:
            client = Path(tmp); (client/"desk").mkdir()
            if smoke:
                (work/"input"/"notice").write_text("采购代号 "+secrets.token_hex(4))
            for turn in ([1] if smoke else ROUNDS):
                if smoke:
                    prompt = "请用共享盘 shell 读 input/notice 的采购代号，在 out/reply.txt 写入完整原文并告诉我结果。"
                elif level:
                    prompt = advanced.release(work, turn, variant, level, seed)
                else:
                    prompt = release(work,turn,variant)
                (run/"trace"/f"prompt-{turn}.txt").write_text(prompt)
                n = claude_turn(run,turn,backend,gw,session,prompt,client,image_id=manifest.get("docker_image"))
                freeze(run,turn)
                entry = {"turn":turn,"upstream_calls":n}
                if level:
                    entry["public_digest"] = advanced.public_digest(work, prompt)
                manifest["turns"].append(entry)
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
    p.add_argument("--model", choices=[MODEL, "qwen3.8-flash"], default=MODEL)
    p.add_argument("--level", type=int, choices=[0, 1, 2, 3], default=0)
    p.add_argument("--seed", type=int, default=0)
    args=p.parse_args()
    if len(set(args.variants))!=len(args.variants):
        p.error("Use each variant at most once per destination")
    dest=args.dest.resolve(); dest.mkdir(parents=True,exist_ok=True)
    url, key_name = URL, "ARK_API_KEY"
    if args.model == "qwen3.8-flash":
        from urllib.parse import urlsplit
        base = os.environ.get("DEEPSEEK_BASE_URL", "").rstrip("/")
        parts = urlsplit(base)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            p.error("Set DEEPSEEK_BASE_URL to the Qwen provider's API base URL")
        url, key_name = base + "/chat/completions", "DEEPSEEK_API_KEY"
    key=os.environ.get(key_name) or getpass.getpass(f"{key_name} (hidden): ")
    with ThreadPoolExecutor(max_workers=len(args.variants)) as pool:
        batch=[pool.submit(play,dest/v,v,args.backend,key,args.smoke,args.limit,
                           model=args.model,url=url,level=args.level,seed=args.seed) for v in args.variants]
        for item in batch:
            item.result()


if __name__ == "__main__":
    main()
