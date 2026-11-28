"""Deployed v1 application. Run python3 project/portal.py serve [port]."""
import argparse
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sqlite3
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo


def events(db, start, end, channel):
    rows = db.execute("select uid, starts from events order by uid")
    return [dict(uid=u, utc=s, status="CONFIRMED") for u,s in rows if start <= s[:10] <= end]


def local_label(utc, zone):
    return utc[:10] + " " + datetime.fromisoformat(utc).astimezone(ZoneInfo(zone)).strftime("%H:%M")


def route(db, url):
    parts = urlsplit(url)
    query = {k:v[0] for k,v in parse_qs(parts.query).items()}
    rows = events(db, query.get("from","1900"), query.get("to","2100"), query.get("channel","A"))
    if parts.path == "/api/events":
        return "application/json", json.dumps(rows)
    if parts.path.startswith("/invite/"):
        rows = [r for r in rows if r["uid"] == parts.path.split("/")[-1]]
    elif parts.path != "/":
        raise KeyError("unknown route")
    return "text/html", "<main>" + "".join(
        f'<article data-uid="{escape(r["uid"])}">{local_label(r["utc"],query.get("tz","UTC"))}</article>' for r in rows
    ) + "</main>"


def main():
    p=argparse.ArgumentParser()
    p.add_argument("action", choices=["serve","request","migrate"])
    p.add_argument("value", nargs="?")
    args=p.parse_args()
    db=sqlite3.connect(os.getenv("PORTAL_DB","data/portal.sqlite"))
    if args.action == "migrate":
        db.commit()
    elif args.action == "request":
        print(route(db,args.value)[1])
    else:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    mime, text = route(db,self.path)
                    self.send_response(200)
                except KeyError:
                    mime,text = "text/plain","missing"
                    self.send_response(404)
                self.send_header("Content-Type",mime+"; charset=utf-8")
                self.end_headers()
                self.wfile.write(text.encode())
        HTTPServer(("127.0.0.1",int(args.value or 8090)),Handler).serve_forever()


if __name__ == "__main__":
    main()
