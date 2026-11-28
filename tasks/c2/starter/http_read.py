"""Read the actual loopback server in a fresh process, including its HTML text."""
import socket
import subprocess
import sys
import time
import urllib.request

with socket.socket() as s:
    s.bind(("127.0.0.1",0))
    port=s.getsockname()[1]
proc=subprocess.Popen([sys.executable,"project/portal.py","serve",str(port)],stderr=subprocess.DEVNULL)
try:
    for i in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}"+sys.argv[1],timeout=2) as response:
                print(response.read().decode())
            break
        except urllib.error.URLError:
            if proc.poll() is not None or i==79: raise
            time.sleep(.025)
finally:
    proc.terminate()
    proc.wait()
