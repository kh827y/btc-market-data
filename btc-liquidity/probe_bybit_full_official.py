"""One-off official mainnet Bybit deep book access check; never infer access from documentation."""
import datetime as dt
import json
import pathlib
import urllib.error
import urllib.request

UTC=dt.timezone.utc
now=dt.datetime.now(UTC)
results={}
for host in ("api.bybit.com","api.bytick.com"):
    for category in ("spot","linear"):
        label=host+"/"+category
        url="https://"+host+"/v5/market/full_orderbook?category="+category+"&symbol=BTCUSDT"
        item={"url":url,"checked_at_utc":dt.datetime.now(UTC).isoformat()}
        try:
            req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"BTC-market-data-source-verification/1.0"})
            with urllib.request.urlopen(req,timeout=12) as response:
                content=response.read(12_000_001)
                if len(content)>12_000_000:raise ValueError("oversized full book")
                raw=json.loads(content)
                item["http_status"]=response.status
            if raw.get("retCode")!=0:raise ValueError("retCode "+str(raw.get("retCode"))+" "+str(raw.get("retMsg"))[:70])
            row=raw.get("result") or {}
            bids,asks=row.get("b"),row.get("a")
            if row.get("s")!="BTCUSDT" or not isinstance(bids,list) or not isinstance(asks,list) or len(bids)<1000 or len(asks)<1000:
                raise ValueError("wrong instrument or insufficient native levels")
            stamp=int(row.get("ts",0))
            if abs(dt.datetime.now(UTC).timestamp()*1000-stamp)>120000:
                raise ValueError("stale or missing native timestamp")
            bid1,ask1=float(bids[0][0]),float(asks[0][0])
            low,high=float(bids[-1][0]),float(asks[-1][0])
            mid=(bid1+ask1)/2
            if not 0<low<=bid1<ask1<=high:raise ValueError("invalid bid/ask order")
            item.update({"status":"verified","levels":{"bid":len(bids),"ask":len(asks)},
                "bid_reach_pct":round((mid-low)/mid*100,5),
                "ask_reach_pct":round((high-mid)/mid*100,5),
                "both_sides_1pct":low<=mid*.99 and high>=mid*1.01,
                "exchange_update_id":row.get("u"),"exchange_seq":row.get("seq"),
                "native_time_utc":dt.datetime.fromtimestamp(stamp/1000,UTC).isoformat()})
        except urllib.error.HTTPError as e:
            item.update({"status":"blocked_or_rejected","http_status":e.code,
                        "reason":e.read(300).decode("utf-8","replace")[:180]})
        except Exception as e:
            item.update({"status":"unavailable_or_unverified","reason":str(e)[:180]})
        results[label]=item
path=pathlib.Path("btc-liquidity/data/bybit_official_full_access_probe.json")
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps({"checked_at_utc":dt.datetime.now(UTC).isoformat(),
    "scope":"official mainnet only, same BTCUSDT instrument; no proxies, no mirrors",
    "markets":results},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps({k:{"status":v["status"],"levels":v.get("levels"),"code":v.get("http_status")} for k,v in results.items()}))
