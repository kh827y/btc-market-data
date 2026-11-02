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
    whale_coverage = {}
    try:
        whale_rows = json.loads((ROOT/"whale_history.json").read_text())
        for metric, dated in whale_rows.items():
            dates = sorted(dated)
            whale_coverage[metric] = {
                "daily_observations": len(dates),
                "first_utc_day": dates[0] if dates else None,
                "last_utc_day": dates[-1] if dates else None,
            }
    except Exception as error:
        missing.append("whale_history unavailable: "+str(error)[:100])
    required_whale_history = ("whale_exchange_deposit_volume_btc","whale_exchange_deposit_count")
    whale_has_multiyear_history = all(
        whale_coverage.get(name,{}).get("daily_observations",0)>=730
        for name in required_whale_history
    )
    output={
        "generated_utc":now.isoformat(),
        "components":components,
        "whale_history_coverage":whale_coverage,
        "exact_multiyear_whale_deposit_history_available":whale_has_multiyear_history,
        "missing":sorted(set(missing)),
        "stale":sorted(set(stale)),
        "known_limits":[
            "Bitview long/short holders use UTXO 150d, not 155d entity-weighted",
            "CoinGlass entity-classified whale deposit count and volume do not have verified free multi-year raw daily histories; only accumulated dated observations. CoinGlass 1d/7d/30d changes and historical percentiles are vendor-calculated, not self-recomputed.",
            "Swiss >=50 BTC whale deposit count and concentration are DIFFERENT metrics, with a verified 7-day backfill; never combine with CoinGlass entity-clustered counts.",
            "CoinMetrics exchange transfers are provisional and entity attribution incomplete"
        ]
    }
    (ROOT/"monitor_latest.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps({"missing":output["missing"],"stale":output["stale"]}))
if __name__=="__main__":
    main()
