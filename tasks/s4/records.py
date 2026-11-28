import json


def read_lines(path):
    with path.open() as stream:
        for no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Unreadable {path.name} line {no}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"Expected an object in {path.name} line {no}")
                yield row


def write(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)
