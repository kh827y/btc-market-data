"""Recover genuinely missing Kraken BTC/USD spot taker trades from Kraken REST.

The free Kraken /0/public/Trades API honors historical 'since' timestamps.
Only verified, fully paginated UTC hours are written. Original CryptoHFTData
received-time hourly files are NOT synthesized, and recovered Kraken
trade-time hours retain explicit distinct provenance.
"""
import argparse
import datetime as dt
import decimal
import json
import math
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import collector

UTC=dt.timezone.utc
D=decimal.Decimal
CENT=D("0.01")
VENUE="kraken"
PAIR="XBTUSD"
MAX_PAGES=2400
GAP_FIRST="2026-10-24T15:00:00Z"
GAP_LAST="2026-10-25T13:00:00Z"
def instant(s):return dt.datetime.fromisoformat(s.replace("Z","+00:00"))
def iso(t):return t.strftime("%Y-%m-%dT%H:00:00Z")
def money(v):return float(v.quantize(CENT,rounding=decimal.ROUND_HALF_UP))
def fetch_page(cursor):
    params=urllib.parse.urlencode({"pair":PAIR,"since":cursor,"count":1000})
    url="https://api.kraken.com/0/public/Trades?"+params
    for attempt in range(7):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"BTC-CVD-Verified-Kraken-History/1.0","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=35) as r:
                data=json.load(r)
            if data.get("error"):raise RuntimeError("Kraken API errors: "+str(data["error"])[:180])
            result=data.get("result",{})
            pairs=[v for k,v in result.items() if k!="last" and isinstance(v,list)]
            if len(pairs)!=1 or not isinstance(result.get("last"),str):
                raise RuntimeError("Unexpected Kraken response schema")
            return pairs[0],result["last"]
        except urllib.error.HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt==6:raise
            wait=min(40,4+attempt*6)
            if e.headers.get("Retry-After"):
                try:wait=max(wait,min(60,int(e.headers["Retry-After"])))
                except ValueError:pass
            time.sleep(wait)
        except (urllib.error.URLError,TimeoutError) as e:
            if attempt==6:raise
            time.sleep(min(25,3+attempt*4))
    raise RuntimeError("Unreachable Kraken retry loop")
def recover(repository_root="."):
    root=pathlib.Path(repository_root)
    state=json.loads((root/"btc-spot-cvd/data/state.json").read_text())
    known=state.get("hourly",{}).get(VENUE,{})
    start=instant(GAP_FIRST);last=instant(GAP_LAST)
    target=[start+dt.timedelta(hours=i) for i in range(int((last-start).total_seconds()//3600)+1)]
    missing=[t for t in target if iso(t) not in known]
    if not missing:
        return {"generated_utc":dt.datetime.now(UTC).isoformat(),"venue":VENUE,
                "requested_hours":[],"data":{},"pages":0,"already_complete":True}
    # Download two surrounding fully archived hours as independent source checks.
    left=missing[0]-dt.timedelta(hours=1)
    right=missing[-1]+dt.timedelta(hours=1)
    stop=right+dt.timedelta(hours=1)
    start_ns=int(left.timestamp())*1_000_000_000-1_000_000_000
    cursor=str(start_ns)
    buckets={iso(left+dt.timedelta(hours=i)):{"buy":D(0),"sell":D(0),"trades":0}
             for i in range(int((right-left).total_seconds()//3600)+1)}
    seen=set()
    pages=0;duplicates=0;previous_time=None;last_trade=None;crossed_end=False
    while pages<MAX_PAGES:
        rows,next_cursor=fetch_page(cursor)
        pages+=1
        if not rows:raise RuntimeError("Kraken returned an empty page before end")
        if int(next_cursor)<=int(cursor):
            raise RuntimeError("Kraken historical pagination cursor did not advance")
        for row in rows:
            if not isinstance(row,list) or len(row)<7:
                raise RuntimeError("Kraken trade ID or taker-side missing")
            price=D(str(row[0]));quantity=D(str(row[1]));ts=D(str(row[2]))
            side=row[3];trade_id=str(row[6])
            if not price.is_finite() or not quantity.is_finite() or price<=0 or quantity<=0:
                raise RuntimeError("Invalid Kraken trade price or quantity")
            if side not in ("b","s") or not trade_id:
                raise RuntimeError("Invalid Kraken taker side or trade ID")
            if trade_id in seen:
                duplicates+=1;continue
            seen.add(trade_id)
            if previous_time is not None and ts<previous_time:
                raise RuntimeError("Non-monotonic Kraken trade time across pages")
            previous_time=ts
            last_trade=str(ts)
            if ts>=D(str(stop.timestamp())):
                crossed_end=True
                break
            if ts<D(str(left.timestamp())):continue
            h=int(ts)//3600*3600
            key=iso(dt.datetime.fromtimestamp(h,UTC))
            if key not in buckets:
                raise RuntimeError("Trade hour outside expected Kraken coverage")
            bucket=buckets[key]
            bucket["buy" if side=="b" else "sell"]+=price*quantity
            bucket["trades"]+=1
        if crossed_end:break
        cursor=next_cursor
        if pages%40==0:
            print("Kraken official pages",pages,"distinct trades",len(seen),
                  "latest trade timestamp",last_trade,flush=True)
        time.sleep(1.15)
    if not crossed_end:raise RuntimeError("Could not paginate through final boundary; pages="+str(pages))
    if any(buckets[iso(t)]["trades"]==0 for t in missing):
        raise RuntimeError("Missing UTC hour has no authenticated Kraken trades")
    comparisons=[]
    for t in (left,right):
        k=iso(t)
        if k not in known:continue
        old=known[k]
        if old.get("complete") is not True or old.get("symbol")!="BTC_USD":continue
        new=buckets[k]
        gross=float(new["buy"]+new["sell"])
        if gross<=0:continue
        original_gross=float(old["buy"])+float(old["sell"])
        original_net=float(old["net"])
        new_net=float(new["buy"]-new["sell"])
        gross_error=abs(gross-original_gross)/max(gross,original_gross)
        net_error=abs(new_net-original_net)/max(gross,original_gross)
        comparisons.append({"hour":k,"source_gross":round(original_gross,2),
                            "kraken_rest_gross":round(gross,2),
                            "gross_relative_error":round(gross_error,6),
                            "net_to_gross_error":round(net_error,6),
                            "close":gross_error<0.05 and net_error<0.05})
    if not comparisons or not any(x["close"] for x in comparisons):
        raise RuntimeError("Kraken REST vs CryptoHFTData adjacent-hour validation failed: "+str(comparisons))
    recovered={}
    for t in missing:
        k=iso(t);b=buckets[k]
        buy=money(b["buy"]);sell=money(b["sell"])
        recovered[k]={"buy":buy,"sell":sell,"net":money(b["buy"]-b["sell"]),
          "trades":b["trades"],"complete":True,"source":"Kraken official public REST Trades",
          "symbol":"BTC_USD","quote":"USD","hour":k,"hour_basis":"trade_time",
          "provenance_note":"Kraken exchange trade-time, not CryptoHFTData received-time"}
    return {"generated_utc":dt.datetime.now(UTC).isoformat(),
            "venue":VENUE,"symbol":"BTC_USD","source":"Kraken official public REST Trades",
            "methodology":"verified full UTC hour by trade timestamp; no zero-filled hours",
            "requested_hours":[iso(t) for t in missing],"data":recovered,
            "pages":pages,"unique_trade_ids":len(seen),"duplicates_skipped":duplicates,
            "independent_adjacent_hour_checks":comparisons,"already_complete":False}
def merge(output,repository_root="."):
    root=pathlib.Path(repository_root)
    data=json.loads(pathlib.Path(output).read_text())
    if data.get("venue")!=VENUE or data.get("source")!="Kraken official public REST Trades":
        if data.get("already_complete") is True:return
        raise ValueError("Unexpected recovery provenance")
    if set(data["requested_hours"])!=set(data["data"]):
        raise ValueError("Missing recovered hourly records")
    state_path=root/"btc-spot-cvd/data/state.json"
    state=json.loads(state_path.read_text())
    kraken=state.setdefault("hourly",{}).setdefault(VENUE,{})
    added=[]
    for hour,rec in data["data"].items():
        if (rec.get("hour")!=hour or rec.get("complete") is not True
            or rec.get("symbol")!="BTC_USD" or rec.get("quote")!="USD"
            or rec.get("source")!="Kraken official public REST Trades"
            or rec.get("hour_basis")!="trade_time"
            or not isinstance(rec.get("trades"),int) or rec["trades"]<=0
            or not all(isinstance(rec.get(k),(int,float)) and math.isfinite(rec[k]) for k in ("buy","sell","net"))
            or rec["buy"]<0 or rec["sell"]<0 or abs(rec["buy"]-rec["sell"]-rec["net"])>0.04):
            raise ValueError("Unverified Kraken hourly trade record: "+hour)
        if hour not in kraken:
            kraken[hour]=rec;added.append(hour)
    now=dt.datetime.now(UTC)
    output_latest=collector.summarise(state,now,[])
    state_path.write_text(json.dumps(state,separators=(",",":"))+"\n")
    (root/"btc-spot-cvd/data/latest.json").write_text(json.dumps(output_latest,indent=2)+"\n")
    status_path=root/"btc-spot-cvd/data/full_backfill_status.json"
    status=json.loads(status_path.read_text()) if status_path.exists() else {}
    status.update({"merged_utc":now.isoformat(),
      "kraken_official_recovered_hours":sorted(set(status.get("kraken_official_recovered_hours",[])+added)),
      "kraken_official_recovery_pages":data.get("pages"),
      "kraken_recovery_source":"Kraken official public REST Trades; exchange trade-time UTC hours",
      "kraken_recovery_validation":data.get("independent_adjacent_hour_checks",[]),
      "complete_alternative_5":{k:v["fixed_five_ex_coinbase"]["complete"] for k,v in output_latest["windows"].items()},
      "complete_original_5":{k:v["complete"] for k,v in output_latest["windows"].items()},
      "note":"CryptoHFTData received-time hours and recovered Kraken exchange trade-time hours are separately labelled; no fabricated or zero-filled hours. Coinbase is outside the alternative five."})
    status_path.write_text(json.dumps(status,indent=2)+"\n")
    print("MERGED",len(added),"Kraken verified REST hours; complete alternative 5:",
          status["complete_alternative_5"],flush=True)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out")
    p.add_argument("--merge")
    args=p.parse_args()
    if args.out:
        result=recover()
        path=pathlib.Path(args.out);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2)+"\n")
        print("RECOVERY",json.dumps({k:v for k,v in result.items() if k!="data"}),flush=True)
    elif args.merge:merge(args.merge)
    else:p.error("Use --out or --merge")
if __name__=="__main__":main()
