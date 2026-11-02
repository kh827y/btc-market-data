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
import pyarrow.compute as pc
import zstandard as zstd

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-liquidity/data")
API="https://api.cryptohftdata.com/v1/download"
ARCHIVE_START=dt.date(2025,6,28)
DAYS=(dt.datetime.now(UTC).date()-ARCHIVE_START).days
BANDS=(0.01,0.05,0.2,1.0)
SEARCH_HOURS=(12,11,13)  # Keep comparable daily observations within the 11-14 UTC window.
SOURCE_RECHECK_DAYS=7
MARKETS={
    "binance_spot":("BTCUSDT","spot",1.0,"USDT"),
    "bybit_spot":("BTCUSDT","spot",1.0,"USDT"),
    "bitget_spot":("BTCUSDT","spot",1.0,"USDT"),
    "okx_spot":("BTC-USDT","spot",1.0,"USDT"),
    "binance_futures":("BTCUSDT","perpetual",1.0,"USDT"),
    "bybit":("BTCUSDT","perpetual",1.0,"USDT"),
    "okx_futures":("BTC-USDT-SWAP","perpetual",0.01,"USDT"),
}

_LAST_REQUEST_AT=0.0
def download(url, limit=45_000_000):
    """Pace anonymous API requests and obey Retry-After on explicit rate limit."""
    global _LAST_REQUEST_AT
    request=urllib.request.Request(url,headers={"User-Agent":"BTC-market-data-independent-historical-L2/1.0"})
    for attempt in range(3):
        delay=1.1-(time.monotonic()-_LAST_REQUEST_AT)
        if delay>0:time.sleep(delay)
        _LAST_REQUEST_AT=time.monotonic()
        try:
            with urllib.request.urlopen(request,timeout=65) as response:
                chunks=[]; total=0
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    total+=len(chunk)
                    if total>limit:raise ValueError("File exceeds 45 MB cap; not silently truncated")
                    chunks.append(chunk)
                return b"".join(chunks)
        except urllib.error.HTTPError as err:
            if err.code not in (429,500,502,503,504) or attempt==2:raise
            value=err.headers.get("Retry-After","") if err.headers else ""
            wait=float(value) if value.replace(".","",1).isdigit() else 5+5*attempt
            time.sleep(max(1,min(wait,60)))
    raise RuntimeError("unreachable retry state")

def decode_parquet(blob):
    # Historical vendor archive objects can be a WHOLE .parquet compressed
    # again as a Zstandard frame (28 B5 2F FD). Recent hours are plain Parquet.
    if blob.startswith(bytes.fromhex("28b52ffd")):
        max_output=350_000_000
        with zstd.ZstdDecompressor().stream_reader(io.BytesIO(blob)) as reader:
            parts=[]; size=0
            while True:
                chunk=reader.read(2_000_000)
                if not chunk:break
                size+=len(chunk)
                if size>max_output:
                    raise ValueError("decompressed Parquet exceeds 350MB safety cap")
                parts.append(chunk)
            blob=b"".join(parts)
    if not blob.startswith(b"PAR1") or not blob.endswith(b"PAR1"):
        raise ValueError("unsupported historical archive payload (neither Parquet nor Zstandard-wrapped Parquet)")
    return blob

def parse_checkpoint(blob,venue,symbol,kind,multiplier,quote,day,hour=12):
    """Only extract a genuine full vendor snapshot, including one later in the file.

    Order-book updates before the first snapshot cannot establish complete depth.
    Do NOT infer complete depth by replaying unanchored updates from an empty book.
    """
    blob=decode_parquet(blob)
    target=dt.datetime.combine(day,dt.time(hour),tzinfo=UTC)
    with pq.ParquetFile(io.BytesIO(blob)) as f:
        required=("received_time","event_type","side","price","quantity","final_update_id")
        if not set(required).issubset(set(f.schema.names)):
            raise ValueError("schema mismatch")
        # Binance may publish the same REST snapshot in multiple receive-time
        # halves. Use the native event_time + last_update_id grouping instead.
        # Other venues lacking these fields fall back to final_update_id.
        extras=[x for x in ("event_time","last_update_id") if x in f.schema.names]
        columns=required+tuple(extras)
        # Most legacy hours contain NO verified checkpoint at all. Scan only
        # the small event_type column first, avoiding conversion of millions of
        # unrelated full-depth update rows to Python objects.
        found=False
        for flags in f.iter_batches(batch_size=131072,columns=["event_type"]):
            if pc.any(pc.equal(flags.column(0),"snapshot")).as_py():
                found=True
                break
        if not found:
            raise ValueError("no verified checkpoint snapshot found anywhere in the requested UTC hour")
        bids={};asks={}
        checkpoint=None
        checkpoint_received=None
        rows=0
        done=False
        for batch in f.iter_batches(batch_size=8192,columns=columns):
            data=batch.to_pydict()
            for i in range(batch.num_rows):
                typ=data["event_type"][i]
                if checkpoint is None:
                    if typ!="snapshot":
                        continue
                    timestamp=int(data["received_time"][i])
                    stamp=dt.datetime.fromtimestamp(timestamp/1e9,UTC)
                    if not target<=stamp<target+dt.timedelta(hours=1):
                        raise ValueError("snapshot timestamp outside requested file hour")
                    received_id=data["final_update_id"][i]
                    source_event=data["event_time"][i] if "event_time" in extras else None
                    native_last=data["last_update_id"][i] if "last_update_id" in extras else None
                    checkpoint=(source_event,native_last) if source_event is not None and native_last is not None else (received_id,)
                    checkpoint_received=timestamp
                    bids={};asks={};rows=0
                source_event=data["event_time"][i] if "event_time" in extras else None
                native_last=data["last_update_id"][i] if "last_update_id" in extras else None
                received_id=data["final_update_id"][i]
                key=(source_event,native_last) if source_event is not None and native_last is not None else (received_id,)
                if typ!="snapshot" or key!=checkpoint:
                    done=True
                    break
                side=data["side"][i]
                if side=="noop":
                    raise ValueError("empty initial book snapshot, no verifiable depth")
                if side not in ("bid","ask"):
                    raise ValueError("unexpected snapshot side")
                p=float(data["price"][i]);q=float(data["quantity"][i])*multiplier
                if not math.isfinite(p) or not math.isfinite(q) or p<=0 or q<=0:
                    raise ValueError("invalid snapshot price/size")
                target_side=bids if side=="bid" else asks
                if p in target_side:
                    # Older Binance archives may contain a byte-for-byte
                    # duplicate REST snapshot; do not double-count it.
                    if target_side[p]==q:continue
                    raise ValueError("conflicting duplicate price inside native snapshot")
                target_side[p]=q
                rows+=1
            if done:break
    if checkpoint is None:
        raise ValueError("no verified checkpoint snapshot found anywhere in the requested UTC hour")
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
    stamp=dt.datetime.fromtimestamp(checkpoint_received/1e9,UTC)
    return {"time":stamp.isoformat(),"venue":venue,"symbol":symbol,"market":kind,"quote":quote,
            "source":"CryptoHFTData historical verified L2 snapshot",
            "file_path":f"{venue}/{day}/{hour:02d}/{symbol}_orderbook.parquet",
            "method":"first genuine complete vendor snapshot in UTC file (may follow unanchored updates); not a daily median",
            "sample_utc_hour":hour,"snapshot_rows":rows,
            "levels":{"bid":len(bids),"ask":len(asks)},
            "mid":round(mid,3),"spread_bps":round(spread,3),
            "reach_pct":{"bid":round(reach_bid,5),"ask":round(reach_ask,5)},
            "bands":bands,
            "quantity_multiplier_to_btc":multiplier,
            "contract_multiplier_caveat":"Historical 0.01 BTC/contract assumed; confirm historical OKX ctVal" if venue=="okx_futures" else None}

def read(path,default):
    try:return json.loads(path.read_text(encoding="utf8"))
    except FileNotFoundError:return default

def write(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(content,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf8")

def verified_entry(entry,venue,day):
    """Only an observed native snapshot is counted; legacy inferred books are unverified."""
    if not isinstance(entry,dict) or entry.get("status")!="ok":
        return False
    data=entry.get("data")
    if not isinstance(data,dict):
        return False
    if (data.get("source")!="CryptoHFTData historical verified L2 snapshot"
        or data.get("method")!="first genuine complete vendor snapshot in UTC file (may follow unanchored updates); not a daily median"
        or data.get("venue")!=venue
        or data.get("symbol")!=MARKETS[venue][0]
        or data.get("market")!=MARKETS[venue][1]
        or data.get("snapshot_rows",0)<20
        or not isinstance(data.get("bands"),dict)
        or not all(k in data["bands"] for k in ("0.01","0.05","0.2","1.0"))):
        return False
    try:
        stamp=dt.datetime.fromisoformat(data["time"])
        return (stamp.tzinfo is not None and stamp.astimezone(UTC).date().isoformat()==day
                and stamp.astimezone(UTC).hour in SEARCH_HOURS
                and data.get("sample_utc_hour")==stamp.astimezone(UTC).hour
                and data.get("file_path","").startswith(f"{venue}/{day}/"))
    except (ValueError,KeyError,TypeError):
        return False

def targets(through, existing, failures=None, now=None):
    """Search real 12:00, 11:00, 13:00 UTC anchors; retry gaps after source updates.

    Failed candidate *hours* are tracked separately so an unanchored 12:00 file
    cannot poison the whole calendar day. Never mark a day completed until a
    verified checkpoint has been measured.
    """
    failures=failures or {}
    now=now or dt.datetime.now(UTC)
    # Complete the most recent 30 actual dates FIRST. Earlier order placed
    # sparse 90/365d comparators ahead of 24-29d recent missing days.
    priority=list(range(31))+[60,90,180,365,31,32,33,89,179,364]
    days=list(dict.fromkeys([through-dt.timedelta(days=n) for n in
                             list(priority)+list(range((through-ARCHIVE_START).days+1))
                             if ARCHIVE_START<=through-dt.timedelta(days=n)<=through]))
    for day in days:
        for venue in MARKETS:
            day_key=day.isoformat()
            previous_entry=existing.get(venue,{}).get(day_key,{})
            if verified_entry(previous_entry,venue,day_key):
                continue  # Strict source snapshot verified; no need to redownload.
            # Legacy "hour-start checkpoint" rows may be inferred from
            # unanchored updates. Retain for audit but do NOT treat as verified.
            for hour in SEARCH_HOURS:
                key=f"{venue}:{day_key}:{hour:02d}"
                failure=failures.get(key,{})
                retry_after=failure.get("retry_after")
                if retry_after:
                    try:
                        if dt.datetime.fromisoformat(retry_after)>now:continue
                    except ValueError:pass
                yield (venue,day,hour)

def recent_coverage(markets,through,windows=(7,30,90,365)):
    """Actual observed date coverage, not percentage of entire vendor history."""
    result={}
    for width in windows:
        dates={(through-dt.timedelta(days=d)).isoformat()
               for d in range(width) if through-dt.timedelta(days=d)>=ARCHIVE_START}
        result[str(width)+"d"]={}
        for venue,rows in markets.items():
            observed=len(dates.intersection(rows))
            result[str(width)+"d"][venue]={"verified_days":observed,
                  "eligible_days":len(dates),
                  "coverage_pct":round(100*observed/len(dates),2) if dates else 0}
    return result

def make_comparisons(records):
    comparisons={}
    baselines={}
    for venue,by_day in records.items():
        dates=sorted(day for day,x in by_day.items() if x.get("status")=="ok")
        if not dates:continue
        newest=dates[-1]
        latest=by_day[newest]["data"]
        comparisons[venue]={"latest_day":newest,"bands":{},"previous_days":{}}
        for lag in (1,7,30,90,365):
            base=(dt.date.fromisoformat(newest)-dt.timedelta(days=lag)).isoformat()
            item=by_day.get(base,{}).get("data")
            if item is not None:
                current_time=dt.datetime.fromisoformat(latest["time"])
                previous_time=dt.datetime.fromisoformat(item["time"])
                hour_offset=abs(((current_time-previous_time)-dt.timedelta(days=lag)).total_seconds())/3600
            else:
                hour_offset=None
            if item is None or hour_offset>0.5:
                comparisons[venue]["previous_days"][str(lag)+"d"]=None
                continue
            deltas={}
            for band in BANDS:
                k=str(band)
                a,b=latest["bands"].get(k),item["bands"].get(k)
                if not a or not b or a["bid_share"] is None or b["bid_share"] is None:
                    continue
                deltas[k]={"bid_change_pct":round(100*(a["bid_usd"]/b["bid_usd"]-1),2) if b["bid_usd"] else None,
                           "ask_change_pct":round(100*(a["ask_usd"]/b["ask_usd"]-1),2) if b["ask_usd"] else None,
                           "bid_share_change_pp":round(100*(a["bid_share"]-b["bid_share"]),3)}
            comparisons[venue]["previous_days"][str(lag)+"d"]={"baseline_day":base,"baseline_time":item["time"],"latest_time":latest["time"],
                                                                     "clock_offset_hours":round(hour_offset,3),
                                                                     "bands":deltas} if deltas else None
        for period,minimum in ((7,5),(30,20),(90,60),(365,240)):
            sub=[by_day[day]["data"] for day in dates
                 if 0<=(dt.date.fromisoformat(newest)-dt.date.fromisoformat(day)).days<period
                 and abs((dt.datetime.fromisoformat(latest["time"])
                          -dt.datetime.fromisoformat(by_day[day]["data"]["time"])
                          -dt.timedelta(days=(dt.date.fromisoformat(newest)-dt.date.fromisoformat(day)).days)
                         ).total_seconds())<=1800]
            row={"days":period,"available":len(sub),"required":minimum,"bands":{}}
            for band in BANDS:
                k=str(band)
                values=[v["bands"][k] for v in sub
                        if v["bands"].get(k,{}).get("bid_share") is not None]
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
    # The daily anchor is for *yesterday*, once all 11/12/13 UTC files have closed.
    through=(now-dt.timedelta(days=1)).date()
    history=read(ROOT/"hft_history.json",{"schema_version":2,"markets":{},"failures":{}})
    markets=history.setdefault("markets",{})
    for market in MARKETS:
        markets.setdefault(market,{})
    if history.get("schema_version",1)<2:
        # Legacy errors were keyed by day, permanently excluded valid alternate
        # hours, and predated support for mid-file checkpoints and zstd wrapping.
        history["failures"]={}
        history["schema_version"]=2
    failures=history.setdefault("failures",{})
    files=0;good=0;errors=[];exclusions=0
    start=time.monotonic()
    limit=int(os.getenv("HFT_MAX_FILES","70"))
    for venue,day,hour in targets(through,markets,failures,now):
        if files>=limit or time.monotonic()-start>700:break
        key=day.isoformat()
        if verified_entry(markets[venue].get(key,{}),venue,key):
            continue  # Genuine snapshot already verified.
        symbol,kind,mul,quote=MARKETS[venue]
        name=f"{venue}/{key}/{hour:02d}/{symbol}_orderbook.parquet"
        url=API+"?"+urllib.parse.urlencode({"file":name})
        files+=1
        try:
            record=parse_checkpoint(download(url),venue,symbol,kind,mul,quote,day,hour=hour)
            markets[venue][key]={"status":"ok","data":record}
            for h in SEARCH_HOURS:
                failures.pop(f"{venue}:{key}:{h:02d}",None)
            good+=1
        except Exception as e:
            reason=f"{type(e).__name__}: {str(e)[:155]}"
            failure_key=f"{venue}:{key}:{hour:02d}"
            failure=failures.setdefault(failure_key,{"attempts":0})
            failure["attempts"]+=1
            failure["checked_at"]=now.isoformat()
            no_snapshot=("no verified checkpoint" in reason)
            # Source may revise old archives. Re-test once per week after a
            # negative completeness check, rather than permanently blacklisting.
            failure["retry_after"]=(now+dt.timedelta(days=SOURCE_RECHECK_DAYS if no_snapshot else 1)).isoformat()
            failure["last_error"]=reason
            errors.append(venue+" "+key+f" {hour:02d}h "+reason)
            exclusions+=1
        if files%10==0:
            print("Checked",files,"historical L2 files; verified",good,
                  "unverifiable",exclusions,flush=True)
    # Bound the failures record to published archive dates (do not lose findings).
    history["updated_at"]=now.isoformat()
    history["schema_version"]=2
    # Never count old inferred/legacy checkpoint records as verified even if
    # they carry status="ok". Only the strict native-snapshot parser can
    # upgrade them. Keep old entries separately for reproducible audit.
    verified_markets={v:{day:row for day,row in markets[v].items()
                         if verified_entry(row,v,day)} for v in MARKETS}
    legacy_unverified={v:len(markets[v])-len(verified_markets[v]) for v in MARKETS}
    comparisons,baselines=make_comparisons(verified_markets)
    source_days=(through-ARCHIVE_START).days+1
    recent_windows=recent_coverage(verified_markets,through)
    coverage={}
    for venue,rows in verified_markets.items():
        coverage[venue]={"verified_days":len(rows),
                         "eligible_days_since_global_start":source_days,
                         "coverage_pct_of_global_window":round(len(rows)/source_days*100,2),
                         "first_verified_day":min(rows,default=None),
                         "latest_verified_day":max(rows,default=None)}
    anchor_keys={v:bool(verified_markets[v].get(through.isoformat())) for v in MARKETS}
    enough_spot=sum(anchor_keys[v] for v in MARKETS if MARKETS[v][1]=="spot")>=2
    enough_perp=sum(anchor_keys[v] for v in MARKETS if MARKETS[v][1]=="perpetual")>=1
    latest={
        "schema_version":2,"generated_at":now.isoformat(),
        "status":"ok" if enough_spot and enough_perp else "partial" if any(verified_markets.values()) else "unavailable",
        "source":"CryptoHFTData historical L2 /download; real observed vendor checkpoint",
        "archive_start":ARCHIVE_START.isoformat(),
        "target_anchor_date":through.isoformat(),
        "searched_utc_hours":list(SEARCH_HOURS),
        "coverage_days":{v:len(rows) for v,rows in verified_markets.items()},
        "legacy_unverified_records":legacy_unverified,
        "coverage":coverage,
        "recent_window_coverage":recent_windows,
        "latest_by_venue":{v:max(rows,default=None) for v,rows in verified_markets.items()},
        "unverifiable_hour_files_total":len(failures),
        "files_attempted_this_run":files,
        "verified_this_run":good,
        "comparison":comparisons,
        "baseline":baselines,
        "errors_recent_run":errors[-20:],
        "caveats":[
            "One real checkpoint per date, typically around 12:00 UTC; not a daily median nor 24h continuous depth.",
            "Daily observations used in comparisons and baseline medians must be within 30 minutes of the same UTC clock time.",
            "Missing checkpoint or insufficient coverage is NOT interpreted as no liquidity; null values are intentional.",
            "Bybit 50-level snapshots are usually too shallow for 0.05%: 0.01% is separately measured and only same-band metrics are comparable.",
            "Market is venue/instrument specific; spot and perpetuals are never pooled or called global.",
            "OKX perpetual 0.01 BTC/contract is assumed historically constant; contract-value history remains unverified.",
            "Legacy hour-start checkpoints without native event_type=snapshot proof are excluded until reverified.",
            "Provider's archives may have gaps and revisions; negative checks retried after 7 days."
        ]
    }
    write(ROOT/"hft_history.json",history)
    write(ROOT/"hft_latest.json",latest)
    print(json.dumps({"status":latest["status"],"files_attempted":files,"verified":good,
                      "unverifiable":exclusions,"coverage":latest["coverage_days"],
                      "errors":errors[:4]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
