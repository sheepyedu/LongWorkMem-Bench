"""Score-free game subprocess. Stdio requests are issued only by the controller."""
from contextlib import contextmanager
import json
import os
import subprocess
import sys

from .league import create

IMAGE = "longworkmem-catan:1"


def serve():
    arena = None
    for line in sys.stdin:
        op, args = json.loads(line)
        try:
            if op == "ready":
                result = {"protocol": "catan-v1"}
            elif op == "open":
                arena = create(**args)
                result = {"state":arena.view(board=True)}
            elif op == "view":
                result = arena.view(**args)
            elif op == "legal":
                result = arena.options()
            elif op == "act":
                result = arena.apply(**args)
            elif op == "end_state":
                result = arena.score_state()
            else:
                raise RuntimeError("Unknown controller operation")
            reply = {"result":result}
        except (ValueError, TypeError) as exc:
            reply = {"error":str(exc)}
        print(json.dumps(reply, ensure_ascii=False, separators=(",",":")),flush=True)


@contextmanager
def connect(image=IMAGE, local=False):
    if local:
        cmd = [sys.executable,"-m","tasks.s4.engine"]
    else:
        cmd = ["docker","run","--rm","-i","--network","none","--read-only","--cap-drop","ALL",
               "--security-opt","no-new-privileges","--memory","512m","--pids-limit","32",
               "-e","PYTHONHASHSEED=0",image]
    env = dict(os.environ,PYTHONHASHSEED="0")
    with subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,encoding="utf-8",env=env) as proc:
        def request(op, **args):
            proc.stdin.write(json.dumps([op,args],ensure_ascii=False)+"\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError(f"S4 engine stopped during {op}")
            return json.loads(line)
        try:
            if request("ready") != {"result":{"protocol":"catan-v1"}}:
                raise RuntimeError("Wrong S4 engine")
            yield request
        finally:
            proc.stdin.close()
            if proc.wait(timeout=15):
                raise RuntimeError("S4 engine process failed")


if __name__ == "__main__":
    serve()
