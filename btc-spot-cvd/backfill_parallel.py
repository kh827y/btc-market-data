"""One-shot real 30d BTC Spot taker-flow backfill, one venue per GitHub runner.

No paid services, no guesses, and no merging of different UTC-hour windows.
The regular incremental collector remains independent. All errors are recorded.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
import collector

UTC=dt.timezone.utc
VENUES=tuple(collector.VENUES)

def atomic_json(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(data,separators=(",",":"),ensure_ascii=False)+"\n",encoding="utf8")
    tmp.replace(p)

def hour_end(now):
    return now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)

def work(venue, output, now=None):
    if venue not in VENUES:raise ValueError("Unsupported venue")
    now=now or dt.datetime.now(UTC)
    end=hour_end(now)
    ex,desired=collector.VENUES[venue]
    sym=collector.symbol(ex,desired)
    out={"venue":venue,"exchange":ex,"symbol":sym,"generated_utc":now.isoformat(),
         "end_utc":collector.key(end),"data":{},"errors":[],"attempted":0}
    # Large published archive: bound requests but allow the full 720h once.
    for i in range(720):
        hour=end-dt.timedelta(hours=i)
        k=collector.key(hour)
        filepath=f"{ex}/{hour:%Y-%m-%d}/{hour:%H}/{sym}_trades.parquet"
        try:
            raw=collector.get(collector.BASE+"/download",params={"file":filepath}).content
            rec=collector.calculate_parquet(raw,hour)
            rec.update({"source":"CryptoHFTData","symbol":sym,
                        "quote":"USDT" if "USDT" in sym else "USD","hour":k})
            out["data"][k]=rec
        except Exception as exc:
            out["errors"].append({"hour":k,"reason":str(exc)[:160]})
        out["attempted"]+=1
        if (i+1)%60==0:
            # Upload only at the end; this checkpoint is local in the runner.
            atomic_json(output,out)
            print(venue,"processed",i+1,"valid",len(out["data"]),"errors",len(out["errors"]),flush=True)
    atomic_json(output,out)
    print("FINAL",venue,"valid",len(out["data"]),"missing",len(out["errors"]),flush=True)

def merge(root, repository_root="."):
    root=Path(root)
    data_path=Path(repository_root)/"btc-spot-cvd/data/state.json"
    latest_path=Path(repository_root)/"btc-spot-cvd/data/latest.json"
    state=json.loads(data_path.read_text(encoding="utf8")) if data_path.exists() else {}
    newest=dt.datetime.now(UTC)
    imported={};errors=[]
    for venue in VENUES:
        path=root/venue/"result.json"
        if not path.is_file():
            raise RuntimeError("Missing runner output for "+venue)
        row=json.loads(path.read_text(encoding="utf8"))
        if row.get("venue")!=venue or row.get("attempted")!=720:
            raise RuntimeError("Incomplete worker manifest: "+venue)
        original=state.setdefault("hourly",{}).setdefault(venue,{})
        added=0
        for hour,record in row["data"].items():
            if record.get("complete") is not True or record.get("hour")!=hour:
                continue
            if hour not in original:
                original[hour]=record;added+=1
        imported[venue]={"new":added,"available":len(original),
                         "worker_missing":len(row.get("errors",[])),
                         "worker_end_utc":row.get("end_utc")}
        errors.extend(venue+" "+v.get("hour","")+": "+v.get("reason","") for v in row.get("errors",[]))
    old=newest-dt.timedelta(days=31)
    for hourly in state.get("hourly",{}).values():
        for k in list(hourly):
            if dt.datetime.fromisoformat(k.replace("Z","+00:00"))<old: del hourly[k]
    out=collector.summarise(state,newest,errors)
    atomic_json(data_path,state)
    atomic_json(latest_path,out)
    atomic_json(Path(repository_root)/"btc-spot-cvd/data/full_backfill_status.json",{
        "merged_utc":newest.isoformat(),"imported":imported,
        "source":"CryptoHFTData public hourly BTC spot trade parquet",
        "complete_original_5":{k:v["complete"] for k,v in out["windows"].items()},
        "complete_alternative_5":{k:v["fixed_five_ex_coinbase"]["complete"] for k,v in out["windows"].items()},
        "note":"Coinbase is not a CryptoHFTData venue. Exact source gaps remain unavailable, never zero."
    })
    print("MERGED",json.dumps(imported),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--venue",choices=VENUES)
    parser.add_argument("--out")
    parser.add_argument("--merge")
    args=parser.parse_args()
    if args.merge:
        merge(args.merge)
    elif args.venue and args.out:
        work(args.venue,args.out)
    else:
        parser.error("Provide --venue and --out, or --merge")
