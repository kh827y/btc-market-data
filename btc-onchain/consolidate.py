"""Compact status feed for BTC onchain monitor."""
import json
import datetime as dt
from pathlib import Path
ROOT = Path("btc-onchain/data")
# Nonessential vendor-specific series: keep dated archive observations but do
# not turn chronic upstream publication lag into a current risk-signal outage.
# The Bitview 150-day UTXO series is distinct from entity 155d cost basis.
REFERENCE_ONLY = {
    ("market_onchain", "sth_realized_price"):
        "BGeometrics source-original STH; delayed free publication",
    ("market_onchain", "lth_realized_price"):
        "BGeometrics source-original LTH; delayed free publication",
    ("market_onchain", "realized_price"):
        "BGeometrics source-original network price; delayed free publication",
    ("whale_deposits", "whale_exchange_deposit_volume_btc"):
        "CoinGlass dated entity-classified whale BTC volume; delayed publication",
}
FILES = {
    "market_onchain":"latest.json",
    "lth_sth_bitview":"bitview_latest.json",
    "whale_deposits":"whale_latest.json",
    "historical_whale_alerts":"whale_alert_latest.json",
}
def main():
    now=dt.datetime.now(dt.timezone.utc)
    components={}
    missing=[]
    stale=[]
    reference_only_delayed=[]
    for name, filename in FILES.items():
        try:
            obj=json.loads((ROOT/filename).read_text())
            born=dt.datetime.fromisoformat(obj["generated_utc"])
            hours=(now-born).total_seconds()/3600
            latest=obj.get("latest",{})
            if name=="historical_whale_alerts":
                day=obj.get("last_observed_day")
                if obj.get("observed_days",0)<365 or not day:
                    raise ValueError("Whale Alert source has insufficient historical dated samples")
                lag=(now.date()-dt.date.fromisoformat(day)).days
                latest={key:{"date":day,"value":value,"lag_days":lag}
                        for key,value in obj.get("last_observed_day_data",{}).items()}
            # The upstream last-run lag_days may be from yesterday. Recompute
            # every observation's TRUE age against today's UTC calendar before
            # deciding its signal eligibility or diagnostic classification.
            for metric,item in latest.items():
                if not isinstance(item,dict):
                    continue
                try:
                    observed=dt.date.fromisoformat(item.get("date",""))
                    item["lag_days"]=(now.date()-observed).days
                except (TypeError,ValueError):
                    item["lag_days"]=None
            components[name]={"feed_age_hours":round(hours,2),"latest":latest,"errors":obj.get("errors",[]),"source":obj.get("source"),"scope":obj.get("scope"),"observed_days":obj.get("observed_days")}
            if hours>36:
                stale.append(name+": feed "+str(round(hours,1))+" hours old")
        except Exception as error:
            missing.append(name+": "+str(error)[:150])
    for name,group in components.items():
        for metric,item in group["latest"].items():
            lag=item.get("lag_days")
            reference_key=(name,metric)
            behind=(item.get("value") is None or
                    not isinstance(lag,int) or lag<0 or lag>3 or
                    item.get("status") in ("missing","delayed","error","stale"))
            if reference_key in REFERENCE_ONLY and behind:
                reference_only_delayed.append({
                    "group":name,"metric":metric,
                    "last_observed_date":item.get("date"),
                    "lag_days":lag,
                    "reason":REFERENCE_ONLY[reference_key],
                    "signal_eligible":False,
                })
                continue
            if item.get("value") is None:
                missing.append(name+":"+metric)
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
    try:
        free_archive=json.loads((ROOT/"whale_alert_latest.json").read_text())
        whale_coverage["whale_alert_observed_exchange_deposits"]={
            "daily_observations":free_archive.get("observed_days",0),
            "first_utc_day":free_archive.get("first_observed_day"),
            "last_utc_day":free_archive.get("last_observed_day"),
            "scope":"only selected public Whale Alert social notifications, not all whale deposits",
        }
    except Exception as error:
        missing.append("whale_alert archive unavailable: "+str(error)[:100])
    whale_has_multiyear_history = all(
        whale_coverage.get(name,{}).get("daily_observations",0)>=730
        for name in required_whale_history
    )
    output={
        "generated_utc":now.isoformat(),
        "components":components,
        "whale_history_coverage":whale_coverage,
        "exact_multiyear_whale_deposit_history_available":whale_has_multiyear_history,
        "historical_public_whale_alert_subset_available":whale_coverage.get("whale_alert_observed_exchange_deposits",{}).get("daily_observations",0)>=730,
        "missing":sorted(set(missing)),
        "stale":sorted(set(stale)),
        "reference_only_delayed":reference_only_delayed,
        "known_limits":[
            "Bitview long/short holders use UTXO 150d, not 155d entity-weighted",
            "CoinGlass entity-classified whale deposit count and volume do not have verified free multi-year raw daily histories; only accumulated dated observations. CoinGlass 1d/7d/30d changes and historical percentiles are vendor-calculated, not self-recomputed.",
            "Swiss >=50 BTC whale deposit count and concentration are DIFFERENT metrics, with a verified 7-day backfill; never combine with CoinGlass entity-clustered counts.",
            "Free Whale Alert official 2018+ history covers selectively published exchange-bound BTC transfer alerts; not all exchange deposits, and yearly alert selection may differ. Never equate it to CoinGlass entity-whale volume/count.",
            "CoinMetrics exchange transfers are provisional and entity attribution incomplete"
        ]
    }
    (ROOT/"monitor_latest.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps({"missing":output["missing"],"stale":output["stale"]}))
if __name__=="__main__":
    main()
