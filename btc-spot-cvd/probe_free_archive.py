"""Bounded spot-trade archive availability probe; reports missing bytes without inventing CVD."""
import datetime as dt
import json
from pathlib import Path
from collector import BASE,VENUES,get,symbol,calculate_parquet,UTC

SAMPLES=("2026-10-04T12:00:00+00:00","2026-10-16T12:00:00+00:00",
         "2026-10-28T12:00:00+00:00","2026-11-01T12:00:00+00:00")

def main():
    results={}
    for venue in ("bitget","binance","okx","bybit","kraken"):
        ex,wants=VENUES[venue]
        rs={}
        try: sym=symbol(ex,wants)
        except Exception as e:
            results[venue]={"symbol_error":str(e)[:160]}
            continue
        for s in SAMPLES:
            hour=dt.datetime.fromisoformat(s)
            path=f"{ex}/{hour:%Y-%m-%d}/{hour:%H}/{sym}_trades.parquet"
            try:
                row=calculate_parquet(get(BASE+"/download",params={"file":path}).content,hour)
                rs[s[:13]]={"ok":True,"trades":row["trades"]}
            except Exception as e:
                rs[s[:13]]={"ok":False,"reason":str(e)[:160]}
        results[venue]={"symbol":sym,"samples":rs}
    output={"at_utc":dt.datetime.now(UTC).isoformat(),"source":"CryptoHFTData public Parquet",
            "note":"Spot checks at four hours do NOT prove completeness of 720 hours",
            "venues":results}
    dest=Path("btc-spot-cvd/data/archive_probe.json")
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps(output,indent=2))

if __name__=="__main__":main()
