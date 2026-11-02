"""BTC derivatives historical feed: exact source/contract/units and coverage."""
import datetime as dt
import json
import math
import pathlib
import urllib.request
from collections import defaultdict

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-derivatives/data")
SHARPE="https://www.sharpe.ai/api"
EXCHANGES=["Binance","Bybit","OKX","Gate","Hyperliquid"]
FUNDING={
    "Binance":("binance","BTCUSDT"),
    "Bybit":("bybit","BTCUSDT"),
    "OKX":("okx","BTC-USDT-SWAP")
}
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"BTC-market-research/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=50) as r:
        return json.load(r)
def number(v):
    x=float(v)
    if not math.isfinite(x):raise ValueError("nonfinite number")
    return x
def dateparse(v):
    return dt.datetime.fromisoformat(str(v).replace("Z","+00:00"))
def status(source,ts,now,max_hours):
    try:age=(now-dateparse(ts)).total_seconds()/3600
    except Exception:return {"source":source,"status":"unknown","age_h":None}
    return {"source":source,"status":"fresh" if 0<=age<=max_hours else "stale","age_h":round(age,2)}
