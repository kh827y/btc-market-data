"""Read-only diagnosis of the 23 missing Kraken BTC/USD UTC trade hours.

This probe DOES NOT mark any hour complete. A provider 404 or a Kraken
recent-trades API returning today's rows is a gap, never zero CVD.
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
import urllib.error

UTC=dt.timezone.utc
FIRST="2026-10-24T15:00:00Z"
LAST="2026-10-25T13:00:00Z"
BASE="https://api.cryptohftdata.com/v1"
def request(url,params=None,stream=False):
    if params: url+="?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":"BTC-CVD-Kraken-Gap-Research/1.0","Accept":"application/json,application/octet-stream"})
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            status=response.status
            raw=response.read(800000) if not stream else response.read(1)
            return {"http":status,"data":raw,"content_type":response.headers.get("Content-Type","")}
    except urllib.error.HTTPError as exc:
        return {"http":exc.code,"error":exc.read(200).decode("utf8","replace")}
    except Exception as exc:
        return {"error":str(exc)[:200]}
def stamp(iso):
    return dt.datetime.fromisoformat(iso.replace("Z","+00:00"))
def main():
    result={"generated_utc":dt.datetime.now(UTC).isoformat(),
      "scope":"diagnostic only; does not certify complete hourly trades",
      "missing_range_utc":[FIRST,LAST],"checks":{}}
    sy=request(BASE+"/symbols",{"exchange":"kraken_spot","data_type":"trades"})
    if sy.get("http")==200:
        try:
            data=json.loads(sy["data"])
            symbols=data.get("symbols",[])
            result["checks"]["hft_symbols"]={"http":200,"btc_symbols":[s for s in symbols if "BTC" in s or "XBT" in s][:30]}
        except Exception as e: result["checks"]["hft_symbols"]={"error":str(e)}
    else:result["checks"]["hft_symbols"]={k:v for k,v in sy.items() if k!="data"}
    for symbol in ("BTC_USD","BTC_USDT"):
        for day,hour in (("2026-10-24","14"),("2026-10-24","15"),("2026-10-25","13"),("2026-10-25","14")):
            file=f"kraken_spot/{day}/{hour}/{symbol}_trades.parquet"
            r=request(BASE+"/download",{"file":file},stream=True)
            result["checks"][file]={k:v for k,v in r.items() if k!="data"}
    for offset in (0,1):
        target=stamp(FIRST)+dt.timedelta(hours=offset)
        # Nanosecond timestamp accepted by Kraken's public Trades since cursor.
        since=str(int(target.timestamp())*1_000_000_000-1_000_000_000)
        r=request("https://api.kraken.com/0/public/Trades",{"pair":"XBTUSD","since":since,"count":1000})
        item={"http":r.get("http"),"error":r.get("error")}
        if r.get("http")==200:
            try:
                d=json.loads(r["data"])
                item["api_errors"]=d.get("error",[])
                pairs=[v for k,v in d.get("result",{}).items() if k!="last" and isinstance(v,list)]
                rows=pairs[0] if pairs else []
                item["count"]=len(rows)
                item["first_utc"]=dt.datetime.fromtimestamp(float(rows[0][2]),UTC).isoformat() if rows else None
                item["last_utc"]=dt.datetime.fromtimestamp(float(rows[-1][2]),UTC).isoformat() if rows else None
                item["taker_sides"]=sorted(set(str(x[3]) for x in rows)) if rows else []
                item["cursor_present"]=bool(d.get("result",{}).get("last"))
                item["matches_requested_hour"]=bool(rows and target<=dt.datetime.fromtimestamp(float(rows[0][2]),UTC)<target+dt.timedelta(hours=1))
            except Exception as exc:item["parse_error"]=str(exc)[:200]
        result["checks"]["kraken_rest_trades_since_"+target.isoformat()]=item
    out=os.environ.get("BTC_CVD_KRAKEN_PROBE_OUTPUT","btc-spot-cvd/data/kraken_gap_probe.json")
    os.makedirs(os.path.dirname(out),exist_ok=True)
    with open(out,"w",encoding="utf8") as f:json.dump(result,f,indent=2,ensure_ascii=False)
    print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
