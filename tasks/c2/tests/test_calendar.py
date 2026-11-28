import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from tasks.c1.runstate import freeze
from tasks.c2 import grade as g
from tasks.c2.pilot import execute
from tasks.c2.scenario import setup,release,write
from tasks.c2.starter.calendar_io import encode
from tasks.c2.subscriber import accept,publish,receipts,interrupt,decode

IMAGE="longworkmem-calendar:1"


class Contract(unittest.TestCase):
    def test_calendar_semantics(self):
        rows=g.expected(4,"A")
        s=encode(reversed(list(rows.values()))).replace("\r\n","\n")
        self.assertEqual(rows,decode(s.encode()))
        for bad in ("",s+s,s.replace("T150000Z","T150000"),s.replace("M42-","K17-")):
            with self.assertRaises(ValueError):decode(bad.encode())

    def test_receipt_identity(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td);setup(run/"work")
            self.assertFalse(accept(run,4,"A","1",{"x":1})["already_received"])
            self.assertTrue(accept(run,4,"A","1",{"x":1})["already_received"])
            with self.assertRaises(ValueError):accept(run,4,"A","1",{"x":2})
            with self.assertRaises(ValueError):publish(run,4,"A","x","../manifest.json")


def reference(run):
    work=run/"work";setup(work)
    ref=Path(g.__file__).with_name("reference")
    portal=work/"project/portal.py"
    for t in range(1,9):
        release(work,t)
        if t==1:
            s=portal.read_text().replace('utc[:10] + " " + datetime.fromisoformat(utc).astimezone(ZoneInfo(zone)).strftime("%H:%M")','datetime.fromisoformat(utc).astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M")')
            portal.write_text(s)
            r=execute(work,"python3 project/http_read.py '/invite/legacy-east?tz=Asia/Tokyo'",IMAGE)
            assert r["status"]==0 and "2026-03-06 08:30" in r["output"]
        if t==2:
            shutil.copytree(ref,work/"project",dirs_exist_ok=True,ignore=shutil.ignore_patterns("__pycache__"))
            s=portal.read_text().replace("def route(db, url):","from service import events, migrate\n\ndef route(db, url):").replace("        db.commit()","        migrate(db)")
            # Detail pages constrain the returned date range to the occurrence.
            s=s.replace('rows = events(db, query.get("from","1900"), query.get("to","2100"), query.get("channel","A"))','rows = events(db, query.get("from","2026-03-01"), query.get("to","2026-06-30"), query.get("channel","A"))')
            portal.write_text(s)
            assert execute(work,"python3 project/portal.py migrate",IMAGE)["status"]==0
        if t==3:
            write(work/"out/preview.json",[dict(uid=k,local=v["utc"][:16].replace("T"," ")) for k,v in g.expected(3,"A").items()])
        if t>=4:
            if t==7:interrupt(run)
            with sqlite3.connect(work/"data/portal.sqlite") as db:
                for ch in ("A","B"):
                    want=g.expected(t,ch,g.APRIL if t==8 else g.MARCH)
                    for k,v in g.changed(g.expected(2,ch,g.APRIL if t==8 else g.MARCH),want).items():
                        db.execute("insert or replace into patch values(?,?,?)",(ch,k,v["utc"]))
                    if t==6 and ch=="B":db.execute("delete from patch where ch='B' and uid='M42-20260320'")
                    delta=g.changed(g.view(receipts(run,ch)),want)
                    if delta:
                        (work/"out/send.ics").write_text(encode(delta.values()))
                        publish(run,t,ch,"urgent-0327-"+ch if t==7 else f"release-{t}-{ch}","out/send.ics")
            if t==8:
                shutil.copyfile(work/"data/portal.sqlite",work/"out/backup.sqlite")
                (work/"out/new-A.ics").write_text(encode(g.expected(t,"A",g.APRIL).values()))
        freeze(work,run/"snapshots"/str(t))
        write(run/"receipts"/f"{t}.json",{ch:receipts(run,ch) for ch in "AB"})
    write(run/"manifest.json",dict(image=IMAGE,status="complete",turns=list(range(1,9))))


@unittest.skipUnless(os.environ.get("C2_TEST_ROOT"),"requires Docker shared directory")
class DockerContract(unittest.TestCase):
    def test_reference_and_faults(self):
        with tempfile.TemporaryDirectory(dir=os.environ["C2_TEST_ROOT"]) as td:
            run=Path(td);reference(run)
            report=g.grade(run)
            self.assertEqual(report["total"],100,[k for k,v in report["checks"].items() if v["fraction"]!=1])
            path=run/"receipts/6.json";logs=json.loads(path.read_text())
            logs["A"].append(dict(turn=6,key="broad-rollback",rows={"M42-20260320":g.expected(6,"B")["M42-20260320"]}))
            logs["B"]=[b for b in logs["B"] if b["turn"]!=6]
            write(path,logs)
            (run/"snapshots/3/out/preview.json").write_text("{")
            (run/"snapshots/8/out/new-A.ics").write_text("broken")
            # Full redundant update changes notifications despite recovering correct state.
            path=run/"receipts/5.json";logs=json.loads(path.read_text())
            logs["A"].append(dict(turn=5,key="repeat",rows=g.expected(5,"A")))
            write(path,logs)
            bad=g.grade(run)["checks"]
            for k in ("scope.A","scope.B","withdraw.A","withdraw.B","preview.local","fresh.subscription","delta.A"):
                self.assertEqual(bad[k]["points"],0,k)
            self.assertEqual(bad["temporary.A"]["fraction"],1)
