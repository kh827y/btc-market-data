"""Independently audit 24h/168h/720h fixed-five spot taker CVD.

Reads the actual UTC-hour records, recomputes venue totals, then compares
the published source and monitor bridge. Never certifies based on tests or
the aggregate complete flag alone.
"""
import datetime as dt
import json
import math
import pathlib

UTC=dt.timezone.utc
VENUES=["binance","okx","bybit","kraken","bitget"]
WINDOWS=[24,168,720]
def when(value):return dt.datetime.fromisoformat(value.replace("Z","+00:00"))
def key(t):return t.strftime("%Y-%m-%dT%H:00:00Z")
def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def close(a,b,eps=0.10):return numeric(a) and numeric(b) and abs(a-b)<=eps
def read(p):return json.loads(pathlib.Path(p).read_text())
def verify(root="."):
    root=pathlib.Path(root)
    state=read(root/"btc-spot-cvd/data/state.json")
    source=read(root/"btc-spot-cvd/data/latest.json")
    bridge=read(root/"btc-monitor/data/brief.json")
    now=dt.datetime.now(UTC)
    end=when(source["last_complete_hour"])
    start=end-dt.timedelta(hours=719)
    report={"verified_utc":now.isoformat(),"source_generated_utc":source.get("generated_utc"),
            "bridge_as_of_utc":bridge.get("as_of_utc"),
            "end_hour_utc":key(end),"start_hour_utc":key(start),
            "venues":VENUES,"windows":{},"missing_hours":{},"invalid_records":[],
            "source_issues":[],"bridge_issues":[],"status":"incomplete"}
    src_age=(now-when(source["generated_utc"])).total_seconds()/3600
    bridge_age=(now-when(bridge["as_of_utc"])).total_seconds()/3600
    if not 0<=src_age<=3:report["source_issues"].append("source stale/future: "+str(round(src_age,2))+"h")
    if not 0<=bridge_age<=3:report["bridge_issues"].append("bridge stale/future: "+str(round(bridge_age,2))+"h")
    if end>now-dt.timedelta(hours=1) or end<now-dt.timedelta(hours=4):
        report["source_issues"].append("last completed UTC hour outside safe 1-4h range")
    for venue in VENUES:
        history=state.get("hourly",{}).get(venue,{})
        expected_symbol=state.get("symbols",{}).get(venue)
        absent=[]
        for i in range(720):
            hour=key(end-dt.timedelta(hours=i))
            rec=history.get(hour)
            if rec is None:
                absent.append(hour);continue
            if (rec.get("complete") is not True or rec.get("hour")!=hour
                or rec.get("symbol")!=expected_symbol
                or rec.get("quote") not in ("USD","USDT")
                or not isinstance(rec.get("trades"),int) or rec["trades"]<=0
                or not all(numeric(rec.get(n)) for n in ("buy","sell","net"))
                or rec["buy"]<0 or rec["sell"]<0
                or not close(rec["net"],rec["buy"]-rec["sell"],0.045)
                or rec.get("source") not in ("CryptoHFTData","Kraken official public REST Trades")
                or (rec.get("source")=="Kraken official public REST Trades" and
                    (venue!="kraken" or rec.get("hour_basis")!="trade_time"))):
                report["invalid_records"].append(venue+":"+hour)
        report["missing_hours"][venue]=sorted(absent)
    for size in WINDOWS:
        label=str(size)+"h"
        times=[key(end-dt.timedelta(hours=i)) for i in range(size)]
        per={};sums={}
        for venue in VENUES:
            history=state.get("hourly",{}).get(venue,{})
            present=[history[k] for k in times if k in history]
            valid=not any(x.startswith(venue+":") and x.split(":",1)[1] in times for x in report["invalid_records"])
            complete=len(present)==size and valid
            total=round(math.fsum(rec["net"] for rec in present),2) if complete else None
            per[venue]={"complete":complete,"hours":len(present),"required":size,"net":total}
            sums[venue]=total
            published=source.get("windows",{}).get(label,{}).get("by_venue",{}).get(venue,{})
            if published.get("complete") is not complete or published.get("hours")!=len(present) or (complete and not close(published.get("net"),total)):
                report["source_issues"].append(label+":"+venue+":published venue mismatch")
        full=all(x["complete"] for x in per.values())
        total=round(math.fsum(sums.values()),2) if full else None
        alt=source.get("windows",{}).get(label,{}).get("fixed_five_ex_coinbase",{})
        if alt.get("complete") is not full or alt.get("venues")!=VENUES or (full and not close(alt.get("net"),total)):
            report["source_issues"].append(label+":fixed five aggregate mismatch")
        recovered=sum(state.get("hourly",{}).get("kraken",{}).get(k,{}).get("source")
                      =="Kraken official public REST Trades" for k in times)
        if alt.get("kraken_official_rest_hours")!=recovered or alt.get("kraken_hour_basis_mixed") is not (recovered>0):
            report["source_issues"].append(label+":Kraken source provenance count mismatch")
        brow=bridge.get("spot_cvd",{}).get("windows",{}).get(label,{})
        balt=brow.get("fixed_five_ex_coinbase",{})
        if (balt.get("complete") is not full or
            (full and (balt.get("venues")!=VENUES or not close(balt.get("net_usd_approx"),total)))):
            report["bridge_issues"].append(label+":bridge fixed five mismatch")
        if balt.get("kraken_official_rest_hours")!=recovered or balt.get("kraken_hour_basis_mixed") is not (recovered>0):
            report["bridge_issues"].append(label+":bridge Kraken source provenance mismatch")
        for venue in VENUES:
            v=brow.get("venue_coverage_hours",{}).get(venue,{})
            if v.get("complete") is not per[venue]["complete"] or v.get("hours")!=per[venue]["hours"]:
                report["bridge_issues"].append(label+":"+venue+":bridge coverage mismatch")
        report["windows"][label]={"complete":full,"net_usd_approx":total,"venues":per}
    feed=bridge.get("sources",{}).get("spot_cvd",{})
    if feed.get("status")!="fresh":report["bridge_issues"].append("spot CVD source is not fresh in bridge")
    if bridge.get("spot_cvd",{}).get("last_complete_hour")!=source.get("last_complete_hour"):
        report["bridge_issues"].append("source and bridge hour differ")
    if when(bridge["as_of_utc"])<when(source["generated_utc"]):
        report["bridge_issues"].append("bridge predates source generation")
    if report["invalid_records"] or report["source_issues"]:
        report["status"]="invalid_source"
    elif not all(report["windows"][str(x)+"h"]["complete"] for x in WINDOWS):
        report["status"]="incomplete"
    elif report["bridge_issues"]:
        report["status"]="bridge_pending_or_invalid"
    else:
        report["status"]="confirmed"
    report["missing_counts"]={k:len(v) for k,v in report["missing_hours"].items()}
    return report
if __name__=="__main__":
    result=verify()
    out=pathlib.Path("btc-spot-cvd/data/verification.json")
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("missing_hours","invalid_records")},ensure_ascii=False))
