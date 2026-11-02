"""Coinbase BTC-USD full 30-day CVD: parallel verified trade-ID slices.

No proxies or paid data. An official Coinbase Exchange REST cursor can seek
directly to an arbitrary past trade ID, so shard by time and seek with a
monotone binary search, then traverse *every* trade in that interval.
All 1,000-ID pages and cross-page boundaries must be contiguous. A time
window is complete only if BOTH sides are actually crossed.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import requests
import sys
import time

UTC=dt.timezone.utc
URL="https://api.exchange.coinbase.com/products/BTC-USD/trades"
SLICE_HOURS=60
SLICES=12
ANCHOR_HOURS=720
REQUEST_TIMEOUT=30
PAGES_MAX=4000

def utc(v):
    t=dt.datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("Naive UTC time")
    return t.astimezone(UTC)

def hour_key(t):
    return t.strftime("%Y-%m-%dT%H:00:00Z")

def fetch(session, after=None, limit=1000):
    params={"limit":limit}
    if after is not None:params["after"]=str(after)
    for attempt in range(4):
        try:
            r=session.get(URL,params=params,timeout=REQUEST_TIMEOUT)
            if r.status_code in (429,500,502,503,504):
                wait=r.headers.get("Retry-After")
                try:delay=min(35,max(1,float(wait)))
                except (TypeError, ValueError):delay=min(25,3*(2**attempt))
                if attempt==3:raise RuntimeError("Coinbase persistent HTTP "+str(r.status_code))
                time.sleep(delay)
                continue
            r.raise_for_status()
            rows=r.json()
            if not isinstance(rows,list) or not rows:
                raise ValueError("Coinbase empty/invalid trade page")
            ids=[int(row["trade_id"]) for row in rows]
            if len(set(ids))!=len(ids) or any(a-b!=1 for a,b in zip(ids,ids[1:])):
                raise ValueError("Coinbase trade IDs missing within page")
            header=r.headers.get("CB-AFTER")
            if header is None or int(header)!=ids[-1]:
                raise ValueError("Coinbase CB-AFTER not last trade ID")
            # Exchange-issued timestamps must be monotone with trade IDs.
            times=[utc(row["time"]) for row in rows]
            if any(a<b for a,b in zip(times,times[1:])):
                raise ValueError("Coinbase timestamp not descending with trade ID")
            return rows,ids,times,header
        except (requests.ConnectionError,requests.Timeout) as ex:
            if attempt==3:raise
            time.sleep(min(25,2*(2**attempt)))
    raise RuntimeError("unreachable fetch retry end")

def seek(session,boundary,trace=None):
    """Return cursor immediately AFTER first trade >= upper time.

    f(after=id) is the ID immediately OLDER than id. Monotone bisect
    finds last cursor for which f(cursor).time < upper boundary.
    """
    head,ids,ts,_=fetch(session,limit=1)
    hi=ids[0]+2
    lo=max(2,hi-50_000_000)
    def instant(cursor):
        rows,ids,ts,_=fetch(session,after=cursor,limit=1)
        return ts[0]
    for _ in range(6):
        if instant(lo)<boundary:break
        lo=max(2,lo-50_000_000)
    else:raise RuntimeError("Cannot find historical seek lower bound")
    if instant(hi)<boundary:raise RuntimeError("Current Coinbase head older than window end")
    count=0
    while hi-lo>1 and count<40:
        mid=(lo+hi)//2
        if instant(mid)>=boundary:hi=mid
        else:lo=mid
        count+=1
    if hi-lo!=1:raise ValueError("Coinbase historical seek not resolved")
    # Independently verify the two trades around the upper UTC boundary.
    before=instant(hi)
    older=instant(lo)
    if not older<boundary<=before:
        raise ValueError("Coinbase history seek time did not bracket cutoff")
    if trace is not None: trace.update({"seek_bisect_queries":count+4,
        "cursor":lo, "older_timestamp":older.isoformat(),
        "newer_timestamp":before.isoformat()})
    return lo

def accumulate(rows, times, lower, upper, buckets):
    below=False
    for tr,t in zip(rows,times):
        if t>=upper:raise ValueError("Coinbase seek emitted trade at/after segment upper boundary")
        if t<lower:
            below=True
            break
        k=hour_key(t)
        b=buckets.setdefault(k,{"buy":0.0,"sell":0.0,"trades":0,
                                  "newest_trade_id":None,"oldest_trade_id":None})
        trade_id=int(tr["trade_id"])
        if b["newest_trade_id"] is None:
            b["newest_trade_id"]=trade_id
        b["oldest_trade_id"]=trade_id
        price=float(tr["price"]);size=float(tr["size"])
        if not (math.isfinite(price) and math.isfinite(size) and price>0 and size>0):
            raise ValueError("Invalid Coinbase trade price or size")
        maker=tr["side"]
        if maker not in ("buy","sell"):raise ValueError("Coinbase trade maker side unknown")
        b["buy" if maker=="sell" else "sell"]+=price*size
        b["trades"]+=1
    return below

def worker(shard,anchor,output,limit_pages=PAGES_MAX,session=None):
    if shard not in range(SLICES):raise ValueError("Unknown shard")
    if anchor.minute or anchor.second or anchor.microsecond:raise ValueError("Anchor must start UTC hour")
    upper=anchor+dt.timedelta(hours=1-shard*SLICE_HOURS)
    lower=upper-dt.timedelta(hours=SLICE_HOURS)
    if upper>dt.datetime.now(UTC)-dt.timedelta(hours=1):
        raise ValueError("Unclosed/current hour cannot be used for archival scan")
    own=session is None
    session=session or requests.Session()
    session.headers.update({"User-Agent":"btc-verified-coinbase-spot-history/1.0"})
    seek_stats={}
    cursor=seek(session,upper,seek_stats)
    buckets={}
    first_id=None
    previous_id=None
    count=0
    page_count=0
    crossed_lower=False
    started=time.monotonic()
    try:
        for n in range(limit_pages):
            rows,ids,times,after=fetch(session,after=cursor,limit=1000)
            if previous_id is not None and ids[0]!=previous_id-1:
                raise ValueError(f"Coinbase consecutive page ID discontinuity {previous_id}/{ids[0]}")
            if first_id is None:first_id=ids[0]
            previous_id=ids[-1]
            page_count+=1
            count+=len(rows)
            crossed_lower=accumulate(rows,times,lower,upper,buckets)
            cursor=int(after)
            if n%125==0:print(json.dumps({"shard":shard,"page":n+1,
                     "oldest_time":times[-1].isoformat(),"elapsed_s":round(time.monotonic()-started)}),flush=True)
            if crossed_lower:break
        if not crossed_lower:
            raise RuntimeError(f"Coinbase shard {shard} exhausted {limit_pages} pages before lower bound")
        expected=[hour_key(lower+dt.timedelta(hours=k)) for k in range(SLICE_HOURS)]
        missing=[k for k in expected if k not in buckets]
        if missing:raise ValueError("No executed trades during Coinbase BTC-USD UTC hours "+str(missing[:8]))
        completed={}
        for k in expected:
            b=buckets[k]
            buy=round(b["buy"],2);sell=round(b["sell"],2)
            completed[k]={"buy":buy,"sell":sell,"net":round(buy-sell,2),
                         "trades":b["trades"],"complete":True,
                         "source":"Coinbase Exchange public REST BTC-USD validated ID-continuous scan",
                         "symbol":"BTC-USD","quote":"USD","hour":k,
                         "time_basis":"exchange_trade_time",
                         "integrity":"id_continuous_verified",
                         "newest_trade_id":b["newest_trade_id"],
                         "oldest_trade_id":b["oldest_trade_id"]}
        res={"schema":1,"status":"verified","anchor_hour":hour_key(anchor),
             "shard":shard,"lower":lower.isoformat(),"upper":upper.isoformat(),
             "verified_utc":dt.datetime.now(UTC).isoformat(),
             "source":"Official Coinbase Exchange public REST historical BTC-USD trades",
             "source_url":URL,"hourly":completed,
             "trade_scan":{"ids_contiguous":True,"page_count":page_count,
                 "trades_scanned":count,"first_id":first_id,"last_id":previous_id,
                 "upper_boundary_bracketed":True,"lower_boundary_crossed":True,
                 "seek":seek_stats,"hours_verified":len(completed)}}
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        Path(output).write_text(json.dumps(res,separators=(",",":"),allow_nan=False)+"\n")
        print(json.dumps({"shard":shard,"hours":len(completed),
                  "pages":page_count,"trades":count,"status":"verified"}),flush=True)
        return res
    finally:
        if own:session.close()

def merge(root,anchor):
    # Input artifacts are generated at one immutable anchor, each range
    # independently covers exactly its 60 hours. Missing shards fail closed.
    slices=[]
    for i in range(SLICES):
        p=Path(root)/f"shard_{i}"/"result.json"
        a=json.loads(p.read_text())
        if (a.get("status")!="verified" or a.get("shard")!=i or
            a.get("anchor_hour")!=hour_key(anchor) or
            len(a.get("hourly",{}))!=SLICE_HOURS or
            a.get("trade_scan",{}).get("ids_contiguous") is not True or
            a.get("trade_scan",{}).get("lower_boundary_crossed") is not True):
            raise ValueError("Unverifiable missing Coinbase shard "+str(i))
        slices.append(a)
    allhours={}
    for sl in slices:
        for hour,row in sl["hourly"].items():
            if hour in allhours:raise ValueError("Duplicated Coinbase shard UTC hour: "+hour)
            if row.get("integrity")!="id_continuous_verified" or row.get("trades",0)<1:
                raise ValueError("Unverified Coinbase UTC trade hour: "+hour)
            allhours[hour]=row
    if len(allhours)!=ANCHOR_HOURS:raise ValueError("Expected precisely 720 Coinbase verified hours")
    expected={hour_key(anchor-dt.timedelta(hours=k)) for k in range(ANCHOR_HOURS)}
    if set(allhours)!=expected:raise ValueError("Coinbase 30d archive has unobserved UTC hours")
    # Enforce trade-ID continuity BETWEEN independently collected shards.
    for a,b in zip(slices,slices[1:]):
        # Shards ordered newest to oldest, so oldest ID in a must be exactly
        # one greater than the newest ID in b (no omissions at boundaries).
        if a["trade_scan"]["last_id"]!=b["trade_scan"]["first_id"]+1:
            # Each shard scans at least one record BELOW its end, so this
            # alone can introduce double-count of boundary proof trades.
            # Validate per-hour extrema directly instead.
            newer=allhours[hour_key(anchor-dt.timedelta(hours=(a["shard"]+1)*SLICE_HOURS-1))]
            older=allhours[hour_key(anchor-dt.timedelta(hours=(b["shard"])*SLICE_HOURS))]
            if newer["oldest_trade_id"]!=older["newest_trade_id"]+1:
                raise ValueError("Coinbase ID discontinuity across shard boundary")
    statepath=Path("btc-spot-cvd/data/state.json")
    state=json.loads(statepath.read_text())
    existing=state.setdefault("hourly",{}).setdefault("coinbase",{})
    mismatches=[]
    for k,row in allhours.items():
        old=existing.get(k)
        if old and old.get("complete"):
            delta=abs(float(old["net"])-row["net"])
            if delta>max(1,abs(row["net"])*0.00001):
                mismatches.append({"hour":k,"prior_source":old.get("source"),
                                   "prior_net":old.get("net"),"verified_net":row["net"]})
        existing[k]=row
    now=dt.datetime.now(UTC)
    # The original snapshot anchor may have rolled; hourly collector will
    # continue catching the new recent hours. No false complete flag.
    sys.path.insert(0,str(Path(__file__).parent))
    from collector import summarise
    result=summarise(state,now,[])
    result["coinbase_integrity"]={"status":"verified","snapshot_anchor":hour_key(anchor),
        "verified_hours_at_snapshot":len(allhours),"shards":SLICES,
        "source":"Coinbase Exchange official REST BTC-USD",
        "trade_id_continuity":"all shard pages + cross-shard boundaries",
        "older_hour_comparisons_changed":len(mismatches)}
    status={"generated_utc":now.isoformat(),"status":"complete_snapshot",
       "anchor_hour":hour_key(anchor),"venue":"Coinbase Exchange BTC-USD",
       "verified_hours_at_snapshot":len(allhours),"pages":sum(x["trade_scan"]["page_count"] for x in slices),
       "trades_scanned":sum(x["trade_scan"]["trades_scanned"] for x in slices),
       "shards":SLICES,"integrity":"coinbase_trade_ids_continuous_including_shard_boundaries",
       "current_24h_complete":result["windows"]["24h"]["complete"],
       "current_168h_complete":result["windows"]["168h"]["complete"],
       "current_720h_complete":result["windows"]["720h"]["complete"],
       "current_last_hour":result["last_complete_hour"],
       "replaced_prior_different_aggregates":mismatches[:50],
       "caveat":"Source trade-time windows differ from CryptoHFTData receiver-time windows on other venues"}
    statepath.write_text(json.dumps(state,separators=(",",":"))+"\n")
    Path("btc-spot-cvd/data/latest.json").write_text(json.dumps(result,indent=2)+"\n")
    Path("btc-spot-cvd/data/coinbase_full_backfill_status.json").write_text(json.dumps(status,indent=2)+"\n")
    print(json.dumps({"merged_hours":len(allhours),"prior_mismatches":len(mismatches),
                      "complete_24h":result["windows"]["24h"]["complete"],
                      "complete_168h":result["windows"]["168h"]["complete"],
                      "complete_720h":result["windows"]["720h"]["complete"]}),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--shard",type=int)
    parser.add_argument("--anchor",required=True)
    parser.add_argument("--output",default="out/result.json")
    parser.add_argument("--merge-dir")
    a=parser.parse_args()
    anchor=utc(a.anchor)
    if a.merge_dir:merge(a.merge_dir,anchor)
    else:worker(a.shard,anchor,a.output)

if __name__=="__main__":main()
