"""Compact status feed for BTC onchain monitor."""
import json
import datetime as dt
from pathlib import Path
ROOT = Path("btc-onchain/data")
FILES = {
    "market_onchain":"latest.json",
    "lth_sth_bitview":"bitview_latest.json",
    "whale_deposits":"whale_latest.json",
}
def main():
    now=dt.datetime.now(dt.timezone.utc)
    components={}
    missing=[]
    stale=[]
    for name, filename in FILES.items():
        try:
            obj=json.loads((ROOT/filename).read_text())
            born=dt.datetime.fromisoformat(obj["generated_utc"])
            hours=(now-born).total_seconds()/3600
            components[name]={"feed_age_hours":round(hours,2),"latest":obj.get("latest",{}),"errors":obj.get("errors",[])}
            if hours>36:
                stale.append(name+": feed "+str(round(hours,1))+" hours old")
        except Exception as error:
            missing.append(name+": "+str(error)[:150])
    for name,group in components.items():
        for metric,item in group["latest"].items():
            if item.get("value") is None:
                missing.append(name+":"+metric)
            lag=item.get("lag_days")
            if isinstance(lag,int) and lag>3:
                stale.append(name+":"+metric+": "+str(lag)+" days")
        for issue in group["errors"]:
            missing.append(name+":"+str(issue.get("metric",issue.get("name","unknown"))))
    output={
        "generated_utc":now.isoformat(),
        "components":components,
        "missing":sorted(set(missing)),
        "stale":sorted(set(stale)),
        "known_limits":[
            "Bitview long/short holders use UTXO 150d, not 155d entity-weighted",
            "Whale deposit raw daily history accumulates only since first successful observation",
            "CoinMetrics exchange transfers are provisional and entity attribution incomplete"
        ]
    }
    (ROOT/"monitor_latest.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps({"missing":output["missing"],"stale":output["stale"]}))
if __name__=="__main__":
    main()
