"""One-off documented free BGeometrics realized-price availability probe.

Three explicit requests, no API key, no expensive retry loops. Do not confuse
'endpoint returned HTTP success' with 'source observation is fresh'.
"""
import datetime as dt
import json
from pathlib import Path
from urllib import error,request

SLUGS=("lth-realized-price","sth-realized-price","realized-price")
def run():
 now=dt.datetime.now(dt.timezone.utc)
 report={"checked_utc":now.isoformat(),"source":"https://bitcoin-data.com/v1/",
         "metrics":{},"scope":"single real request for each of three public API endpoints; not a bypass of rate limits"}
 for slug in SLUGS:
    url=f"https://bitcoin-data.com/v1/{slug}?startday=2026-10-20"
    try:
        req=request.Request(url,headers={"User-Agent":"BTC-Onchain-Free-Source-Integrity/1.0",
                                        "Accept":"application/json"})
        with request.urlopen(req,timeout=35) as res:
            raw=res.read(700000)
            code=res.status
        response=json.loads(raw)
        if not isinstance(response,list):
            raise ValueError("non-list metric payload: "+str(type(response).__name__))
        rows=[x for x in response if isinstance(x,dict) and x.get("d")]
        report["metrics"][slug]={"http_status":code,"rows":len(rows),
                  "latest_date":max((r["d"] for r in rows),default=None),
                  "field_names":sorted({key for r in rows[-1:] for key in r})}
    except error.HTTPError as exc:
        report["metrics"][slug]={"http_status":exc.code,"error":"HTTP "+str(exc.code)}
    except Exception as exc:
        report["metrics"][slug]={"error":type(exc).__name__+": "+str(exc)[:180]}
 path=Path("btc-onchain/data/bgeometrics_probe.json")
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps(report))
if __name__=="__main__":run()
