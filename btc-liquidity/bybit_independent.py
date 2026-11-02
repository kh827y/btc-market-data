"""Independent verified historical Bybit BTC L2 depth from public daily ZIP files.

Fetch ONLY a range at the beginning of each ZIP: the initial *actual full*
order-book snapshot can be inflated from the first deflate member without
fetching/redistributing hundreds of megabytes of copyrighted vendor data.
This is a midnight instantaneous snapshot, not a daily liquidity average.
"""
import datetime as dt
import json
import math
import os
import pathlib
import re
import statistics
import struct
import time
import urllib.error
import urllib.request
import zlib

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-liquidity/data")
BASE="https://quote-saver.bycsi.com/orderbook"
BANDS=(0.01,0.05,0.2,1.0)
VENUES={"bybit_independent_spot":("spot",dt.date(2025,4,29)),
        "bybit_independent_linear":("linear",dt.date(2023,1,18))}
LINEAR_500_LAST=dt.date(2025,8,20)

def source_url(category,day):
    depth=500 if category=="linear" and day<=LINEAR_500_LAST else 200
    return f"{BASE}/{category}/BTCUSDT/{day.isoformat()}_BTCUSDT_ob{depth}.data.zip",depth

def range_bytes(url,length=524288):
    req=urllib.request.Request(url,headers={
        "User-Agent":"BTC-independent-archive-research/1.0",
        "Range":f"bytes=0-{length-1}"})
    with urllib.request.urlopen(req,timeout=40) as resp:
        if resp.status!=206:raise ValueError("source did not honor byte-range request")
        rng=resp.headers.get("Content-Range","")
        match=re.fullmatch(r"bytes 0-(\\d+)/(\\d+)",rng)
        if not match:raise ValueError("invalid Content-Range: "+rng)
        final,total=map(int,match.groups())
        expected=min(length,total)
        if final+1!=expected:raise ValueError("invalid range end")
        body=resp.read(length+1)
        if len(body)!=expected:raise ValueError("short or oversized HTTP range")
    return body

def first_zip_snapshot(prefix,expected_symbol="BTCUSDT"):
    if len(prefix)<30 or prefix[:4]!=b"PK\x03\x04":
        raise ValueError("not a ZIP local file header")
    _,_,flags,method,_,_,_,_,_,name_len,extra_len=struct.unpack_from("<IHHHHHIIIHH",prefix,0)
    if flags&1:raise ValueError("encrypted ZIP entry")
    if method!=8:raise ValueError("ZIP member must use deflate")
    start=30+name_len+extra_len
    if start>=len(prefix):raise ValueError("incomplete ZIP local entry")
    name=prefix[30:30+name_len].decode("utf8","strict")
    if "/" in name or ".." in name or not name.endswith(".data"):
        raise ValueError("unexpected archive member name")
    # ZIP member may be far larger than the range. Inflate only the first
    # complete newline-delimited message. Do not claim full ZIP CRC verification.
    head=zlib.decompressobj(-15).decompress(prefix[start:],max_length=2_000_000)
    line=head.split(b"\n",1)[0]
    if len(line)>1_000_000 or not line:raise ValueError("first snapshot message too large/absent")
    if b"\n" not in head:raise ValueError("incomplete first snapshot; fetch larger range")
    obj=json.loads(line)
    if obj.get("type")!="snapshot" or obj.get("data",{}).get("s")!=expected_symbol:
        raise ValueError("first archive message is not a genuine BTCUSDT snapshot")
    if not str(obj.get("topic","")).startswith("orderbook."):
        raise ValueError("unexpected order book topic")
    for field in ("u","seq"):
        val=obj["data"].get(field)
        if not isinstance(val,int) or val<0:
            raise ValueError("invalid source sequence field "+field)
    return obj

def measure(obj,day,venue,depth,source):
    ts=int(obj["ts"])
    stamp=dt.datetime.fromtimestamp(ts/1000,UTC)
    start=dt.datetime.combine(day,dt.time(0),UTC)
    age=(stamp-start).total_seconds()
    if age<0 or age>180:
        raise ValueError("initial snapshot not near midnight UTC")
    data=obj["data"]
    levels={}
    for side,field in (("bid","b"),("ask","a")):
        raw=data[field]
        if not isinstance(raw,list) or len(raw)<min(30,depth):
            raise ValueError("too few levels for "+side)
        parsed=[]
        for row in raw:
            if len(row)<2:raise ValueError("invalid order level")
            p=float(row[0]);q=float(row[1])
            if not all(math.isfinite(x) and x>0 for x in (p,q)):
                raise ValueError("invalid nonpositive order level")
            parsed.append((p,q))
        descending=side=="bid"
        if any((a<=b if descending else a>=b) for (a,_),(b,_) in zip(parsed,parsed[1:])):
            raise ValueError("unsorted/duplicated order levels")
        if len(parsed)>depth:
            raise ValueError("more levels than advertised exchange depth")
        levels[side]=parsed
    bids=levels["bid"];asks=levels["ask"]
    if bids[0][0]>=asks[0][0]:raise ValueError("crossed initial order book")
    mid=(bids[0][0]+asks[0][0])/2
    spread=(asks[0][0]-bids[0][0])/mid*10000
    if spread>40:raise ValueError("abnormal snapshot spread")
    reach_b=(mid-bids[-1][0])/mid*100
    reach_a=(asks[-1][0]-mid)/mid*100
    bands={}
    for band in BANDS:
        have_b=reach_b>=band
        have_a=reach_a>=band
        b=sum(p*q for p,q in bids if p>=mid*(1-band/100)) if have_b else None
        a=sum(p*q for p,q in asks if p<=mid*(1+band/100)) if have_a else None
        bands[str(band)]={
            "bid_usd":round(b,2) if b is not None else None,
            "ask_usd":round(a,2) if a is not None else None,
            "bid_coverage_complete":have_b,
            "ask_coverage_complete":have_a,
            "bid_share":round(b/(a+b),5) if b is not None and a is not None and a+b>0 else None,
        }
    return {"time":stamp.isoformat(),"market":"spot" if venue.endswith("spot") else "perpetual",
            "venue":venue,"symbol":"BTCUSDT","source":source,"source_type":"independent Bybit daily native snapshot",
            "ob_levels_declared":depth,"levels":{"bid":len(bids),"ask":len(asks)},
            "mid_usd_approx":round(mid,3),"spread_bps":round(spread,4),
            "reach_pct":{"bid":round(reach_b,5),"ask":round(reach_a,5)},
            "bands":bands,
            "sequence":{"u":data["u"],"seq":data["seq"]},
            "http_access":"first 512KiB range of source ZIP, partial deflate; no full-file CRC",
            "source_received_seconds_after_utc_midnight":round(age,3)}

def read(path,default):
    try:return json.loads(path.read_text(encoding="utf8"))
    except FileNotFoundError:return default
def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf8")

def candidates(asof,records,failures,now):
    # Interleave source markets BY DATE. Never spend the whole historical
    # backfill budget on perpetuals while starving the spot series.
    offsets=(0,1,7,30,90,180,365,730,1095,2,3,4,5,6,8,14,21,60)
    earliest=min(start for category,start in VENUES.values())
    days=list(dict.fromkeys([asof-dt.timedelta(days=n) for n in
                              list(offsets)+list(range((asof-earliest).days+1))
                              if earliest<=asof-dt.timedelta(days=n)<=asof]))
    for day in days:
        for venue,(category,start) in VENUES.items():
            if day<start:continue
            key=day.isoformat()
            if key in records.get(venue,{}):continue
            failure=failures.get(f"{venue}:{key}",{})
            if failure.get("retry_after","")>now.isoformat():continue
            yield venue,day

def comparisons(records):
    result={}
    for venue,by_day in records.items():
        days=sorted(by_day)
        if not days:continue
        newest=days[-1]
        current=by_day[newest]
        against={}
        for delta in (1,7,30,90,180,365,730,1095):
            prev=(dt.date.fromisoformat(newest)-dt.timedelta(days=delta)).isoformat()
            old=by_day.get(prev)
            if old is None:
                against[str(delta)+"d"]=None;continue
            t1=dt.datetime.fromisoformat(current["time"])
            t0=dt.datetime.fromisoformat(old["time"])
            if abs(((t1-t0)-dt.timedelta(days=delta)).total_seconds())>180:
                against[str(delta)+"d"]=None;continue
            diff={}
            for band in BANDS:
                k=str(band)
                x=current["bands"][k];y=old["bands"][k]
                if x["bid_share"] is None or y["bid_share"] is None:continue
                diff[k]={"bid_change_pct":round((x["bid_usd"]/y["bid_usd"]-1)*100,2),
                         "ask_change_pct":round((x["ask_usd"]/y["ask_usd"]-1)*100,2),
                         "bid_share_change_pp":round((x["bid_share"]-y["bid_share"])*100,3)}
            against[str(delta)+"d"]={"baseline_date":prev,"bands":diff,
                                      "current_time":current["time"],"baseline_time":old["time"]} if diff else None
        result[venue]={"latest":newest,"comparisons":against}
    return result

def main():
    now=dt.datetime.now(UTC)
    asof=(now-dt.timedelta(days=1)).date()
    history=read(ROOT/"bybit_independent_history.json",{"schema_version":1,"records":{},"failures":{}})
    records=history.setdefault("records",{})
    for venue in VENUES:records.setdefault(venue,{})
    failures=history.setdefault("failures",{})
    limit=int(os.getenv("BYBIT_ARCHIVE_MAX_FILES","120"))
    attempted=0;verified=0;errors=[]
    start=time.monotonic()
    for venue,day in candidates(asof,records,failures,now):
        if attempted>=limit or time.monotonic()-start>460:break
        category=VENUES[venue][0]
        url,depth=source_url(category,day)
        attempted+=1
        try:
            obj=first_zip_snapshot(range_bytes(url))
            record=measure(obj,day,venue,depth,url)
            records[venue][day.isoformat()]=record
            failures.pop(f"{venue}:{day}",None)
            verified+=1
        except Exception as exc:
            key=f"{venue}:{day}"
            item=failures.setdefault(key,{"attempts":0})
            item["attempts"]+=1
            item["last_error"]=f"{type(exc).__name__}: {str(exc)[:160]}"
            item["retry_after"]=(now+dt.timedelta(days=1 if item["attempts"]<3 else 7)).isoformat()
            errors.append(key+" "+item["last_error"])
        if attempted%25==0:
            print("Bybit independent archive",attempted,"attempted",verified,"verified",flush=True)
    history["updated_at"]=now.isoformat()
    history["schema_version"]=1
    derived=comparisons(records)
    coverage={}
    for venue,(category,start) in VENUES.items():
        total=(asof-start).days+1
        coverage[venue]={"verified_days":len(records[venue]),"eligible_days":total,
                         "coverage_pct":round(len(records[venue])/total*100,2),
                         "first_verified":min(records[venue],default=None),
                         "latest_verified":max(records[venue],default=None)}
    newest_count=sum(asof.isoformat() in records[v] for v in VENUES)
    latest={"schema_version":1,"generated_at":now.isoformat(),
            "status":"ok" if newest_count==2 else "partial" if newest_count else "unavailable",
            "source":"Bybit official-public archive quote-saver.bycsi.com, not CryptoHFTData",
            "target_day":asof.isoformat(),
            "source_spot_start":"2025-04-29","source_linear_start":"2023-01-18",
            "capture_time":"first source snapshot at or within 180s after 00:00 UTC",
            "snapshot_not_daily_average":True,
            "full_source_crc_verified":False,
            "coverage":coverage,
            "comparisons":derived,
            "errors_recent_run":errors[-12:],
            "attempted_this_run":attempted,"verified_this_run":verified,
            "limitations":["Only first real snapshot each day, not continuous depth or intraday withdrawal",
                           "ZIP range extraction checks first message and valid DEFLATE but not full ZIP CRC",
                           "Bybit depth changed from 500 levels to 200 on 2025-08-21",
                           "Truncated coverage beyond the deepest observed level remains null",
                           "Spot and perpetual contracts are kept separate; USDT approximates USD",
                           "High-frequency depth vs long-horizon BTC trend requires other independent factors"]}
    write(ROOT/"bybit_independent_history.json",history)
    write(ROOT/"bybit_independent_latest.json",latest)
    print(json.dumps({"status":latest["status"],"tried":attempted,"new":verified,
                      "coverage":coverage,"errors":errors[:5]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
