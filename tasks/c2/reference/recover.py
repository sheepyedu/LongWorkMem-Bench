import json,sys
from pathlib import Path
from calendar_io import encode
job,log,ch,target=sys.argv[1:]
order=json.loads(Path(job).read_text())[ch]
rows=[] if any(r["key"]==order["key"] for r in json.loads(Path(log).read_text())) else [{k:v for k,v in order.items() if k!="key"}]
Path(target).write_text(encode(rows))
