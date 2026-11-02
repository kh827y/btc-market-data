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

def fetch_oi(now):
    url=SHARPE+"/futures/data?chart=oi-stacked&coin=BTC&timeframe=1M"
    obj=get(url)
    rows=obj.get("data")
    if not isinstance(rows,list) or not rows:raise ValueError("no BTC OI history")
    history=defaultdict(dict)
    for item in rows:
        venue=item.get("exchange")
        if venue not in EXCHANGES:continue
        try:
            timestamp=dateparse(item["timestamp"])
            usd=number(item["open_interest_value"])
            if usd<=0:continue
        except (KeyError,ValueError,TypeError):continue
        hour=timestamp.strftime("%Y-%m-%dT%H:00:00Z")
        history[hour][venue]=round(usd,2)
    last=max(history)
    latest=history[last]
    complete=set(EXCHANGES).issubset(latest)
    daily={}
    for hour,items in sorted(history.items()):
        if set(EXCHANGES).issubset(items):
            daily[hour[:10]]={"hour":hour, "venues":{name:items[name] for name in EXCHANGES},
                "five_venue_usd":round(sum(items[name] for name in EXCHANGES),2)}
    days=sorted(daily)
    changes={}
    for duration in (1,7,30):
        if not days:
            changes[str(duration)+"d"]=None
            continue
        target=(dt.date.fromisoformat(days[-1])-dt.timedelta(days=duration)).isoformat()
        a=daily.get(days[-1]);b=daily.get(target)
        changes[str(duration)+"d"]=(round((a["five_venue_usd"]/b["five_venue_usd"]-1)*100,3)
             if b and b["five_venue_usd"]>0 else None)
    meta=obj.get("meta") or {}
    asof=meta.get("as_of",last)
    return {"source":"Sharpe Terminal /api/futures/data oi-stacked","unit":"USD notional (vendor normalized)",
        "venues":EXCHANGES,"latest_hour":last,"latest_venue_usd":latest,
        "latest_five_venue_usd":round(sum(latest[name] for name in EXCHANGES),2) if complete else None,
        "daily_history":daily,"available_daily_complete":len(daily),"changes_pct":changes,
        "source_meta":status("Sharpe OI",asof,now,3),
        "provider_warnings":meta.get("warnings",[])}
