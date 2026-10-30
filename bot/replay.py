"""89: event replay for one coin: python3 replay.py <mint-prefix>"""
import sys, json, time
from logger import conn
c = conn()
for r in c.execute("SELECT ts,kind,symbol,version,data FROM events WHERE mint LIKE ? ORDER BY ts", (sys.argv[1] + "%",)):
    print(time.strftime("%H:%M:%S", time.localtime(r["ts"])), r["version"], r["kind"], r["symbol"], r["data"][:220])
