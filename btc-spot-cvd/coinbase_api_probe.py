"""Read-only Coinbase REST pagination and free archive feasibility probe."""
import datetime as dt
import json
import requests
from pathlib import Path
UTC=dt.timezone.utc
S=requests.Session()
S.headers.update({"User-Agent":"BTC-CVD-integrity-probe/1.0"})
out={"tested_utc":dt.datetime.now(UTC).isoformat(),"cases":{}}
url="https://api.exchange.coinbase.com/products/BTC-USD/trades"
def report(tag, params):
    try:
        r=S.get(url, params=params, timeout=30)
        row={"http":r.status_code,"request":params,"cb_after":r.headers.get("CB-AFTER"),"cb_before":r.headers.get("CB-BEFORE"),"rate_limit":r.headers.get("Retry-After")}
        if r.ok:
            a=r.json()
            if isinstance(a,list) and a:
                row.update({"returned":len(a),"newest_trade_id":a[0].get("trade_id"),"oldest_trade_id":a[-1].get("trade_id"),"newest_trade_utc":a[0].get("time"),"oldest_trade_utc":a[-1].get("time"),
                            "ids_strictly_descending":all(int(x["trade_id"])>int(y["trade_id"]) for x,y in zip(a,a[1:])),
                            "adjacent_ids":sum(int(x["trade_id"])==int(y["trade_id"])+1 for x,y in zip(a,a[1:])),
                            "first_last_trade_id_gap":int(a[0]["trade_id"])-int(a[-1]["trade_id"])})
            else:row["returned"]=len(a) if isinstance(a,list) else None
        else:row["reason"]=r.text[:200]
        out["cases"][tag]=row
    except Exception as e:out["cases"][tag]={"error":str(e)[:220]}
report("limit_1000",{"limit":1000})
report("limit_100",{"limit":100})
head=out["cases"].get("limit_1000",{})
if head.get("cb_after"):
    report("after_head",{"limit":1000,"after":head["cb_after"]})
out["interpretation"]={"trade_direction":"Coinbase side denotes maker side, not taker",
                       "what_was_measured":"Actual REST page size and cursor continuity; not aggregate CVD"}
dst=Path("btc-spot-cvd/data/coinbase_api_probe.json")
dst.parent.mkdir(parents=True,exist_ok=True)
dst.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
print(json.dumps(out,ensure_ascii=False))
