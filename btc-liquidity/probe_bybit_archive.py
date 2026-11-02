"""Probe free Bybit public daily level-2 archives without downloading 200+ MB."""
import datetime as dt
import json
import urllib.request
import urllib.error
from html.parser import HTMLParser

class Items(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self, tag, attrs):
        if tag=="a":
            href=dict(attrs).get("href")
            if href:self.links.append(href)

for market in ("linear","spot"):
    base=f"https://quote-saver.bycsi.com/orderbook/{market}/BTCUSDT/"
    try:
        request=urllib.request.Request(base,headers={"User-Agent":"BTC-market-data-quality-probe/1.0"})
        with urllib.request.urlopen(request,timeout=25) as response:
            raw=response.read(160_000)
            status=response.status
        parser=Items();parser.feed(raw.decode("utf-8","replace"))
        print(json.dumps({"market":market,"listing_status":status,
                          "files_count_visible":len(parser.links),
                          "recent_names":[x for x in parser.links if "2026-10-31" in x or "2026-11-01" in x][:10],
                          "old_names":[x for x in parser.links if "2025-06-02" in x or "2024-01-01" in x][:10],
                          "first_links":parser.links[:6]},ensure_ascii=False),flush=True)
    except Exception as exc:print("LIST_ERROR",market,str(exc),flush=True)
    for date,depth in (("2026-10-31",200),("2025-06-02",500)):
        # Do not download huge files merely to confirm reachability.
        name=f"{date}_BTCUSDT_ob{depth}.data.zip"
        url=base+name
        try:
            request=urllib.request.Request(url,headers={"User-Agent":"BTC-market-data-quality-probe/1.0","Range":"bytes=0-16383"})
            with urllib.request.urlopen(request,timeout=35) as response:
                header=dict(response.headers)
                prefix=response.read(16384)
                print(json.dumps({"market":market,"date":date,"code":response.status,
                   "length":header.get("Content-Length"),"range":header.get("Content-Range"),
                   "zip_magic":prefix[:4].hex(),"read":len(prefix),"ctype":header.get("Content-Type")}),flush=True)
        except Exception as exc: print("DOWNLOAD_ERROR",market,date,str(exc),flush=True)

# Full independent archive read: one spot day and one perpetual day, streaming
# downloads to disk. Inspect JSON schema and 12:00 UTC snapshot availability.
import tempfile, zipfile, os, time
for market,date,depth,cap in (("spot","2026-10-31",200,70_000_000),("linear","2026-10-31",200,170_000_000)):
    url=f"https://quote-saver.bycsi.com/orderbook/{market}/BTCUSDT/{date}_BTCUSDT_ob{depth}.data.zip"
    start=time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as home:
            p=os.path.join(home,"book.zip")
            req=urllib.request.Request(url,headers={"User-Agent":"BTC-market-data-quality-probe/1.0"})
            size=0
            with urllib.request.urlopen(req,timeout=80) as response,open(p,"wb") as fp:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    size+=len(chunk)
                    if size>cap:raise RuntimeError("archive exceeds size limit")
                    fp.write(chunk)
            with zipfile.ZipFile(p) as z:
                names=z.namelist()
                if len(names)!=1:raise RuntimeError("unexpected ZIP members")
                first=[];snaps=[];counts={};last=None
                with z.open(names[0]) as f:
                    for i,line in enumerate(f):
                        j=json.loads(line)
                        if len(first)<2:first.append(j)
                        counts[j.get("type","?")]=counts.get(j.get("type","?"),0)+1
                        if j.get("type")=="snapshot":
                            if len(snaps)<8:snaps.append({"ts":j.get("ts"),"cts":j.get("cts"),"topic":j.get("topic"),"bids":len(j.get("data",{}).get("b",[])),"asks":len(j.get("data",{}).get("a",[]))})
                        if i>300000:break
                    print("FULL",market,"download_bytes",size,"members",names,"first",first,
                        "snapshots_first_300k",snaps,"counts_sample",counts,
                        "elapsed_s",round(time.monotonic()-start,2),flush=True)
    except Exception as exc:
        print("FULL_ERROR",market,type(exc).__name__,str(exc)[:240],flush=True)
