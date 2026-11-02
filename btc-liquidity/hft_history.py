"""Historical BTC L2 depth sampled from genuine hourly checkpoint snapshots.
Never call partial depth complete; do not mix spot and perpetual markets.
"""
import datetime as dt
import io
import json
import math
import os
import pathlib
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

import pyarrow.parquet as pq

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-liquidity/data")
API="https://api.cryptohftdata.com/v1/download"
DAYS=90
BANDS=(0.05,0.2,1.0)
MARKETS={
    "binance_spot":("BTCUSDT","spot",1.0,"USDT"),
    "bybit_spot":("BTCUSDT","spot",1.0,"USDT"),
    "okx_spot":("BTC-USDT","spot",1.0,"USDT"),
    "binance_futures":("BTCUSDT","perpetual",1.0,"USDT"),
    "okx_futures":("BTC-USDT-SWAP","perpetual",0.01,"USDT"),
}

def download(url, limit=45_000_000):
    request=urllib.request.Request(url,headers={"User-Agent":"BTC-market-data-independent-historical-L2/1.0"})
    with urllib.request.urlopen(request,timeout=65) as response:
        chunks=[]; total=0
        while True:
            chunk=response.read(1024*1024)
            if not chunk:break
            total+=len(chunk)
            if total>limit:raise ValueError("File exceeds 45 MB cap; not silently truncated")
            chunks.append(chunk)
    return b"".join(chunks)

def parse_checkpoint(blob,venue,symbol,kind,multiplier,quote,day):
    hour=dt.datetime.combine(day,dt.time(12),tzinfo=UTC)
    with pq.ParquetFile(io.BytesIO(blob)) as f:
        columns=("received_time","event_type","side","price","quantity","final_update_id")
        if not set(columns).issubset(set(f.schema.names)):
            raise ValueError("schema mismatch")
        bids={};asks={}
        checkpoint=None
        rows=0
        for batch in f.iter_batches(batch_size=8192,columns=columns):
            data=batch.to_pydict()
            for i in range(batch.num_rows):
                typ=data["event_type"][i]
                if checkpoint is None:
                    if typ!="snapshot":
                        raise ValueError("missing hour-start checkpoint; cannot reconstruct full book from an arbitrary update")
                    checkpoint=(data["received_time"][i],data["final_update_id"][i])
                    stamp=dt.datetime.fromtimestamp(checkpoint[0]/1e9,UTC)
                    if abs((stamp-hour).total_seconds())>60:
                        raise ValueError("checkpoint timestamp not at requested hour")
                if typ!="snapshot" or (data["received_time"][i],data["final_update_id"][i])!=checkpoint:
                    break
                side=data["side"][i]
                if side not in ("bid","ask"):
                    raise ValueError("unexpected snapshot side")
                p=float(data["price"][i])
                q=float(data["quantity"][i])*multiplier
                if not math.isfinite(p) or not math.isfinite(q) or p<=0 or q<=0:
                    raise ValueError("invalid snapshot price/size")
                target=bids if side=="bid" else asks
                if p in target:
                    raise ValueError("duplicate price level in initial checkpoint")
                target[p]=q
                rows+=1
            else:
                continue
            break
    if len(bids)<10 or len(asks)<10:
        raise ValueError("snapshot has fewer than 10 levels on a side")
    best_bid=max(bids);best_ask=min(asks)
    if best_bid>=best_ask:
        raise ValueError("crossed historical checkpoint")
    mid=(best_bid+best_ask)/2
    spread=(best_ask-best_bid)/mid*10000
    if spread>40:
        raise ValueError("abnormal historical checkpoint spread")
    reach_bid=(mid-min(bids))/mid*100
    reach_ask=(max(asks)-mid)/mid*100
    bands={}
    for band in BANDS:
        bid_ok=reach_bid>=band
        ask_ok=reach_ask>=band
        b=sum(p*q for p,q in bids.items() if p>=mid*(1-band/100)) if bid_ok else None
        a=sum(p*q for p,q in asks.items() if p<=mid*(1+band/100)) if ask_ok else None
        bands[str(band)]={"bid_usd":round(b,2) if b is not None else None,
                          "ask_usd":round(a,2) if a is not None else None,
                          "bid_coverage_complete":bid_ok,
                          "ask_coverage_complete":ask_ok,
                          "bid_share":round(b/(a+b),5) if b is not None and a is not None and a+b>0 else None}
    return {"time":hour.isoformat(),"venue":venue,"symbol":symbol,"market":kind,"quote":quote,
            "source":"CryptoHFTData historical verified L2 hour-start checkpoint",
            "file_path":f"{venue}/{day}/12/{symbol}_orderbook.parquet",
            "method":"first complete checkpoint from 12:00 UTC hourly L2 file, not trades or interpolated quotes",
            "snapshot_rows":rows,"levels":{"bid":len(bids),"ask":len(asks)},
            "mid":round(mid,3),"spread_bps":round(spread,3),
            "reach_pct":{"bid":round(reach_bid,5),"ask":round(reach_ask,5)},
            "bands":bands,
            "quantity_multiplier_to_btc":multiplier,
            "contract_multiplier_caveat":"Historical 0.01 BTC/contract assumed; confirm against current OKX ctVal" if venue=="okx_futures" else None}

def read(path,default):
    try:return json.loads(path.read_text(encoding="utf8"))
    except FileNotFoundError:return default

def write(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(content,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf8")

def targets(through, existing):
    # Prioritize meaningful same-hour baselines before filling consecutive 90-day history.
    priority=(0,1,7,30,90,2,3,4,5,6,8,14,21,60)
    days=list(dict.fromkeys([through-dt.timedelta(days=n) for n in
                             list(priority)+list(range(DAYS+1)) if n<=DAYS]))
    return [(venue,day) for day in days for venue in MARKETS
            if day.isoformat() not in existing.get(venue,{})]

def make_comparisons(records):
    comparisons={}
    baselines={}
    for venue,by_day in records.items():
        dates=sorted(day for day,x in by_day.items() if x.get("status")=="ok")
        if not dates:continue
        newest=dates[-1]
        latest=by_day[newest]["data"]
        comparisons[venue]={"latest_day":newest,"bands":{},"previous_days":{}}
        for lag in (1,7,30,90):
            base=(dt.date.fromisoformat(newest)-dt.timedelta(days=lag)).isoformat()
            item=by_day.get(base,{}).get("data")
            if item is None:
                comparisons[venue]["previous_days"][str(lag)+"d"]=None
                continue
            deltas={}
            for band in BANDS:
                k=str(band)
                a,b=latest["bands"][k],item["bands"][k]
                if a["bid_share"] is None or b["bid_share"] is None:continue
                deltas[k]={"bid_change_pct":round(100*(a["bid_usd"]/b["bid_usd"]-1),2) if b["bid_usd"] else None,
                           "ask_change_pct":round(100*(a["ask_usd"]/b["ask_usd"]-1),2) if b["ask_usd"] else None,
                           "bid_share_change_pp":round(100*(a["bid_share"]-b["bid_share"]),3)}
            comparisons[venue]["previous_days"][str(lag)+"d"]={"baseline_day":base,"bands":deltas} if deltas else None
        for period,minimum in ((7,5),(30,20),(90,60)):
            sub=[by_day[day]["data"] for day in dates
                 if 0<=(dt.date.fromisoformat(newest)-dt.date.fromisoformat(day)).days<period]
            row={"days":period,"available":len(sub),"required":minimum,"bands":{}}
            for band in BANDS:
                k=str(band)
                values=[v["bands"][k] for v in sub if v["bands"][k]["bid_share"] is not None]
                if len(values)>=minimum:
                    row["bands"][k]={"median_bid_usd":round(statistics.median(v["bid_usd"] for v in values),2),
                                     "median_ask_usd":round(statistics.median(v["ask_usd"] for v in values),2),
                                     "median_bid_share":round(statistics.median(v["bid_share"] for v in values),5),
                                     "samples":len(values)}
                else:row["bands"][k]=None
            baselines.setdefault(venue,{})[str(period)+"d"]=row
    return comparisons,baselines

def main():
    now=dt.datetime.now(UTC)
    # Hour 12 data is published after that hour closes, so the latest guaranteed date is yesterday.
    through=(now-dt.timedelta(days=1)).date()
    history=read(ROOT/"hft_history.json",{"schema_version":1,"markets":{},"failures":{}})
    markets=history.setdefault("markets",{})
    for market in MARKETS:
        markets.setdefault(market,{})
    failures=history.setdefault("failures",{})
    files=0;good=0;errors=[]
    start=time.monotonic()
    limit=int(os.getenv("HFT_MAX_FILES","70"))
    for venue,day in targets(through,markets):
        if files>=limit or time.monotonic()-start>430:break
        key=day.isoformat()
        if failures.get(venue+":"+key,{}).get("attempts",0)>=3:continue
        symbol,kind,mul,quote=MARKETS[venue]
        name=f"{venue}/{key}/12/{symbol}_orderbook.parquet"
        url=API+"?"+urllib.parse.urlencode({"file":name})
        files+=1
        try:
            record=parse_checkpoint(download(url),venue,symbol,kind,mul,quote,day)
            markets[venue][key]={"status":"ok","data":record}
            failures.pop(venue+":"+key,None)
            good+=1
        except Exception as e:
            reason=f"{type(e).__name__}: {str(e)[:160]}"
            item=failures.setdefault(venue+":"+key,{"attempts":0})
            item["attempts"]+=1
            item["last_error"]=reason
            errors.append(venue+" "+key+" "+reason)
        if files%10==0:print("Processed",files,"historical L2 hours, valid",good,flush=True)
    # Limit mutable archive to roughly 90 days; retain only verified daily snapshots.
    floor=(through-dt.timedelta(days=DAYS)).isoformat()
    for venue in markets:
        markets[venue]={day:x for day,x in sorted(markets[venue].items()) if day>=floor}
    history["updated_at"]=now.isoformat()
    comparisons,baselines=make_comparisons(markets)
    latest={"generated_at":now.isoformat(),"status":"ok" if good or any(markets[k] for k in markets) else "unavailable",
            "source":"CryptoHFTData free historical L2, actual 12:00 UTC orderbook checkpoint",
            "coverage_days":{v:len(x) for v,x in markets.items()},
            "latest_by_venue":{v:max(x,default=None) for v,x in markets.items()},
            "comparison":comparisons,"baseline":baselines,
            "errors_recent_run":errors[-20:],
            "caveats":["Historical hourly file snapshot is a point-in-time book, NOT daily median or full 24h book.",
                       "Missing checkpoint or insufficient band coverage is null; do not infer zero liquidity.",
                       "Venue and spot/perpetual observations are not pooled or presented as whole market.",
                       "OKX perpetual book uses 0.01 BTC/contract; historical denomination assumed constant.",
                       "CryptoHFTData archive has documented gaps and retroactive corrections."] }
    write(ROOT/"hft_history.json",history)
    write(ROOT/"hft_latest.json",latest)
    print(json.dumps({"files_attempted":files,"valid":good,"coverage":latest["coverage_days"],
                      "comparisons":{k:list(v.get("previous_days",{})) for k,v in comparisons.items()},
                      "errors":errors[:6]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
