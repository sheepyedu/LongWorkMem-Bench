"""Isolated text environment. Only prompts and submitted business forms cross stdin/stdout."""
from contextlib import contextmanager
import json
import subprocess
import sys

IMAGE = "longworkmem-circuit:1"


def exchange(process, *values):
    process.stdin.write(json.dumps(values, ensure_ascii=False) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("Circuit container stopped before replying")
    reply = json.loads(line)
    if "invalid_form" in reply:
        raise ValueError(reply["invalid_form"])
    return reply["value"]


@contextmanager
def open_engine(seed, variant, desks, level, qualifiers):
    image = subprocess.check_output(["docker", "image", "inspect", "-f", "{{.Id}}", IMAGE], text=True).strip()
    args = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", image,
            str(seed), variant, str(desks), str(level), str(qualifiers)]
    with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          text=True, encoding="utf-8") as process:
        try:
            if exchange(process, "ready") != 3:
                raise RuntimeError("Unexpected circuit engine version")
            yield process, image
        finally:
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError("Circuit container failed")


def serve():
    from .circuit import Circuit
    seed, variant, desks, level, qualifiers = sys.argv[1:]
    circuit = Circuit(int(seed), variant, int(desks), int(level), int(qualifiers), version=3)
    for line in sys.stdin:
        op, *args = json.loads(line)
        try:
            if op == "ready":
                value = circuit.version
            elif op == "prompt":
                value = circuit.prompt(*args)
            elif op == "submit":
                value = circuit.submission(*args)
            elif op == "empty":
                value = circuit.receipt(args[0], {}, args[1])
            else:
                raise RuntimeError("Unknown engine operation")
            reply = {"value": value}
        except ValueError as exc:
            reply = {"invalid_form": str(exc)}
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    serve()
