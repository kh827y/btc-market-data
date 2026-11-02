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
