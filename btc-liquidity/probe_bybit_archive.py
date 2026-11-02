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
