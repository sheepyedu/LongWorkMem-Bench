"""The participant-facing interface. All events and attachments are frozen outside /office."""

import fcntl
import json
import sys
import re
from pathlib import Path

from tasks.w1.mail import act
from tasks.w1.office import TOOLS as OFFICE_TOOLS, shell, tool
from .scenario import ROUNDS, address, CODES

TOOLS = [
    *OFFICE_TOOLS,
    tool(
        "receipt_query",
        "查询已发生的投递、确认或冻结附件。当前日及更早可查。",
        {
            "case": "主题案号或空字符串查全部",
            "as_of": "六月日号，空表示今天",
            "receipt": "回执号或空字符串；指定回执可读附件",
        },
    ),
]
ALLOWED = {"mcp__office__" + s["name"] for s in TOOLS}


def events(run, day, action="deliver"):
    rows = []
    for path in (run / "mail").glob("*/*/event.json"):
        e = json.loads(path.read_text())
        if e["turn"] <= day and (action is None or e["action"] == action):
            rows.append(e)
    return sorted(rows, key=lambda e: (e["turn"], e["sequence"]))


def status(event, day):
    if event is None:
        return "未发"
    if event.get("unknown_mailbox") and day > event["turn"]:
        return "退信"
    if (
        event["subject"] in ("P03", "P09")
        and event["recipient"].endswith(".service@office.test")
        and day > event["turn"]
    ):
        return "退信"
    delay = 2 if event["subject"] in ("P01", "N03", "U04") else 1
    return "已确认" if day >= event["turn"] + delay else "待确认"


def attachment(run, e):
    return (run / "mail" / str(e["turn"]) / e["receipt"] / "payload").read_bytes()


def invoke(run, t, image, name, args):
    schema = next((s["inputSchema"] for s in TOOLS if s["name"] == name), None)
    if (
        not schema
        or not isinstance(args, dict)
        or set(args) != set(schema["required"])
        or not all(isinstance(v, str) for v in args.values())
    ):
        raise ValueError("请使用工具说明中的参数")
    if name == "shell":
        return shell(
            run / "work", args["command"], "docker", image=image, check_runtime=True
        )
    if name == "receipt_query":
        manifest = run / "manifest.json"
        if (
            manifest.is_file()
            and json.loads(manifest.read_text()).get("protocol") == "w4-release-v4"
        ):
            from .quota.desk import query

            return query(run, t, args)
        raw = args["as_of"].strip()
        match = re.fullmatch(r"(?:(?:06-|6月))?(\d{1,2})(?:日)?", raw)
        if raw and not match:
            raise ValueError("日期示例：4、06-04、6月4日，空字符串表示今天")
        day = int(match[1]) if match else t
        if not 1 <= day <= t:
            raise ValueError("只可查询截至当前业务日的历史")
        result = []
        for e in events(run, day):
            if (
                args["case"]
                and e["subject"] != args["case"]
                or args["receipt"]
                and e["receipt"] != args["receipt"]
            ):
                continue
            row = {**e, "status": status(e, day)}
            if args["receipt"]:
                row["payload"] = attachment(run, e).decode("utf8", errors="replace")[
                    :24000
                ]
            result.append(row)
        return result
    with (run / "mail/.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        seq = len(events(run, t, None)) + 1
        receipt = act(run, t, name, **args, rounds=ROUNDS)
        path = run / "mail" / str(t) / receipt / "event.json"
        e = json.loads(path.read_text())
        e["sequence"] = seq
        manifest = run / "manifest.json"
        if manifest.is_file() and json.loads(manifest.read_text()).get("protocol") in (
            "w4-release-v2",
            "w4-release-v3",
        ):
            known = {
                address(i, role)
                for i in range(len(CODES))
                for role in ("service", "backup")
            }
            if t >= 5:
                known.update(
                    address(i, role) for i in (0, 1) for role in ("new", "review")
                )
            e["unknown_mailbox"] = e["recipient"] not in known
        path.write_text(json.dumps(e, ensure_ascii=False))
    return {"receipt": receipt, "action": name}


def serve(run, t, image):
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method = msg["method"]
        if method == "initialize":
            result = dict(
                protocolVersion=msg["params"]["protocolVersion"],
                capabilities={"tools": {}},
                serverInfo={"name": "office", "version": "1"},
            )
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg["params"]
            try:
                value = invoke(run, t, image, p["name"], p["arguments"])
                result = {
                    "content": [
                        {"type": "text", "text": json.dumps(value, ensure_ascii=False)}
                    ]
                }
            except (ValueError, TypeError, OSError, KeyError) as exc:
                detail = exc.strerror if isinstance(exc, OSError) else str(exc)
                result = {
                    "isError": True,
                    "content": [
                        {"type": "text", "text": detail.replace(str(run), "<office>")}
                    ],
                }
            with (run / "trace" / f"tools-{t}.jsonl").open("a") as log:
                print(
                    json.dumps(
                        dict(name=p["name"], args=p["arguments"], result=result),
                        ensure_ascii=False,
                    ),
                    file=log,
                )
        else:
            result = {}
        print(
            json.dumps(
                dict(jsonrpc="2.0", id=msg["id"], result=result), ensure_ascii=False
            ),
            flush=True,
        )


if __name__ == "__main__":
    serve(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
