"""Verified independent Bybit daily order-book backfill with isolated date shards.

Uses actual historical ZIP first snapshots (partial HTTP byte-range), never
manufactured historical depth. Workers write JSON artifacts; merge revalidates
dates, venues and snapshot provenance before changing the canonical checkpoint.
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import bybit_independent as bi

UTC=dt.timezone.utc
SHARDS={"linear":8,"spot":4}
NAME={"linear":"bybit_independent_linear","spot":"bybit_independent_spot"}

def write(path, obj):
    p=pathlib.Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n",encoding="utf8")

def worker(category,shard,out,through=None):
    if category not in SHARDS or not 0<=shard<SHARDS[category]:
        raise ValueError("invalid venue/shard combination")
    venue=NAME[category]
    earliest=bi.VENUES[venue][1]
    through=through or (dt.datetime.now(UTC)-dt.timedelta(days=1)).date()
    count=(through-earliest).days+1
    rows={};failed={};attempted=0
    # Stable modulo sharding guarantees each calendar date is attempted exactly once.
    for ordinal in range(shard,count,SHARDS[category]):
        day=earliest+dt.timedelta(days=ordinal)
        key=day.isoformat()
        url,depth=bi.source_url(category,day)
        attempted+=1
        obj=None
        try:
            obj=bi.first_zip_snapshot(bi.range_bytes(url))
            rec=bi.measure(obj,day,venue,depth,url)
            rows[key]=rec
        except Exception as e:
            reason=f"{type(e).__name__}: {str(e)[:180]}"
            if obj is not None and "not near midnight" in reason:
                # A genuine but late source snapshot is NOT a valid midnight observation.
                # Preserve the observed timestamp for a defensible source-gap audit.
                stamp=dt.datetime.fromtimestamp(int(obj["ts"])/1000,UTC)
                offset=(stamp-dt.datetime.combine(day,dt.time(),UTC)).total_seconds()
                reason+=f"; first_source_snapshot_utc={stamp.isoformat()}; offset_seconds={offset:.3f}"
            failed[key]=reason
        if attempted%35==0:
            write(out,{"status":"partial","category":category,"venue":venue,
                       "shard":shard,"shards":SHARDS[category],"through":str(through),
                       "attempted":attempted,"records":rows,"errors":failed})
            print("WORK",venue,shard,attempted,"valid",len(rows),"unavailable",len(failed),flush=True)
    write(out,{"status":"done","category":category,"venue":venue,"shard":shard,
               "shards":SHARDS[category],"through":str(through),
               "expected_attempted":len(range(shard,count,SHARDS[category])),
               "attempted":attempted,"records":rows,"errors":failed})
    print("DONE",venue,shard,"verified",len(rows),"errors",len(failed),flush=True)

def merge(artifact_dir,root=".",now=None):
    now=now or dt.datetime.now(UTC)
    asof=(now-dt.timedelta(days=1)).date()
    root=pathlib.Path(root)
    loc=root/"btc-liquidity/data"
    state=bi.read(loc/"bybit_independent_history.json",
                  {"schema_version":1,"records":{},"failures":{}})
    records=state.setdefault("records",{})
    failures=state.setdefault("failures",{})
    stats={}
    common_through=None
    for category,num_shards in SHARDS.items():
        venue=NAME[category]
        start=bi.VENUES[venue][1]
        section=records.setdefault(venue,{})
        seen=set();good=0;bad=0;fresh=0
        for shard in range(num_shards):
            path=pathlib.Path(artifact_dir)/f"{category}-{shard}"/"result.json"
            block=json.loads(path.read_text(encoding="utf8"))
            through=dt.date.fromisoformat(block["through"])
            if common_through is None:common_through=through
            if through!=common_through or not start<=through<=asof:
                raise ValueError("shards have inconsistent or future source through dates")
            total=(through-start).days+1
            expected=set((start+dt.timedelta(days=i)).isoformat()
                         for i in range(shard,total,num_shards))
            observed=set(block["records"])|set(block["errors"])
            if (block.get("status")!="done" or block.get("category")!=category or
                block.get("shard")!=shard or block.get("shards")!=num_shards or
                block.get("attempted")!=len(expected) or observed!=expected or
                set(block["records"])&set(block["errors"])):
                raise ValueError("worker is missing dates or has invalid provenance: "+str(path))
            if seen&observed:raise ValueError("duplicate shard dates")
            seen|=observed
            for day,rec in block["records"].items():
                timestamp=dt.datetime.fromisoformat(rec["time"])
                if (rec.get("venue")!=venue or rec.get("market")!=("spot" if category=="spot" else "perpetual")
                    or not (-0.010 <= (timestamp-dt.datetime.combine(dt.date.fromisoformat(day),dt.time(),UTC)).total_seconds() <= 180)
                    or rec.get("source_type")!="independent Bybit daily native snapshot"
                    or "bands" not in rec):
                    raise ValueError("invalid archived book provenance for "+venue+" "+day)
                if day not in section:
                    section[day]=rec;fresh+=1
                good+=1
                failures.pop(venue+":"+day,None)
            for day,err in block["errors"].items():
                bad+=1
                if day not in section:
                    failures[venue+":"+day]={"attempts":1,"last_error":err,
                       "retry_after":(now+dt.timedelta(days=7)).isoformat()}
        stats[venue]={"verified_in_shards":good,"worker_failures":bad,
                      "new_verified":fresh,"total_verified":len(section),
                      "coverage_through":max(seen,default=None)}
    state["updated_at"]=now.isoformat()
    state["schema_version"]=1
    derived=bi.comparisons(records)
    coverage={}
    for venue,(category,start) in bi.VENUES.items():
        total=max(0,(asof-start).days+1)
        valid=sum(start.isoformat()<=key<=asof.isoformat() for key in records[venue])
        coverage[venue]={"verified_days":valid,"eligible_days":total,
            "coverage_pct":round(valid/total*100,2) if total else 0,
            "first_verified":min(records[venue],default=None),
            "latest_verified":max(records[venue],default=None)}
    # A day is accounted for only when it has a verified original snapshot or
    # a concrete recorded failure. Never infer a missing day is zero liquidity.
    day_audit={}
    for venue,(category,start) in bi.VENUES.items():
        verified=[];unverified=[];unaccounted=[]
        for n in range((asof-start).days+1):
            day=(start+dt.timedelta(days=n)).isoformat()
            if day in records[venue]:verified.append(day)
            elif venue+":"+day in failures:
                unverified.append({"day":day,"reason":failures[venue+":"+day].get("last_error","unknown")})
            else:unaccounted.append(day)
        day_audit[venue]={
            "eligible_days":len(verified)+len(unverified)+len(unaccounted),
            "verified_days":len(verified),"explicit_error_days":len(unverified),
            "unaccounted_days":unaccounted,"source_dates_accounted_for":not unaccounted,
            "unverified_dates":unverified,
            "coverage_7d":sum(d>=(asof-dt.timedelta(days=6)).isoformat() for d in verified),
            "coverage_30d":sum(d>=(asof-dt.timedelta(days=29)).isoformat() for d in verified)}
    newest_count=sum(asof.isoformat() in records[v] for v in bi.VENUES)
    latest={"schema_version":1,"generated_at":now.isoformat(),
        "status":"ok" if newest_count==2 else "partial" if newest_count else "unavailable",
        "source":"Bybit official-public archive quote-saver.bycsi.com, not CryptoHFTData",
        "target_day":asof.isoformat(),"source_spot_start":"2025-04-29",
        "source_linear_start":"2023-01-18",
        "capture_time":"first source snapshot at or within 180s after 00:00 UTC",
        "snapshot_not_daily_average":True,"full_source_crc_verified":False,
        "coverage":coverage,"comparisons":derived,
        "errors_recent_run":[],"attempted_this_run":sum(SHARDS.values()),
        "verified_this_run":sum(x["new_verified"] for x in stats.values()),
        "bulk_import":{"method":"verified per-date original ZIP first snapshot, 8 linear + 4 spot shards",
                       "new_valid_records":sum(x["new_verified"] for x in stats.values())},
        "limitations":["Point-in-time midnight snapshots, not continuous L2 or daily average",
                       "Partial ZIP range validates the initial snapshot, not complete-archive CRC",
                       "200/500 level cap; insufficient band reach stays null",
                       "Spot and perpetual never pooled; USDT approximated as USD"]}
    write(loc/"bybit_independent_history.json",state)
    write(loc/"bybit_independent_latest.json",latest)
    write(loc/"bybit_full_backfill_status.json",{
        "merged_utc":now.isoformat(),"shard_results":stats,"coverage":coverage,
        "worker_source_through":common_through.isoformat(),
        "day_audit":day_audit,
        "all_source_dates_accounted_for":all(x["source_dates_accounted_for"] for x in day_audit.values()),
        "errors_by_venue":{k:v["explicit_error_days"] for k,v in day_audit.items()},
        "completeness_is_per_source_date_not_full_day_orderbook":True})
    print("MERGED",json.dumps(stats),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--category",choices=list(SHARDS));p.add_argument("--shard",type=int)
    p.add_argument("--out");p.add_argument("--merge");p.add_argument("--root",default=".")
    args=p.parse_args()
    if args.merge:
        merge(args.merge,args.root)
    elif args.category is not None and args.shard is not None and args.out:
        worker(args.category,args.shard,args.out)
    else:p.error("specify worker category/shard/out, or --merge")
