"""Probe native Gate BTC_USDT spot REST depth without proxy or substitutes."""
import datetime as dt
import json
import pathlib
import urllib.request
import urllib.error

UTC=dt.timezone.utc
results={}
for limit in (2000,5000,10000):
    label=str(limit)
    url=f"https://api.gateio.ws/api/v4/spot/order_book?currency_pair=BTC_USDT&interval=0&limit={limit}&with_id=true"
    row={"url":url,"checked_at_utc":dt.datetime.now(UTC).isoformat()}
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"BTC-market-data-check/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=22) as resp:
            raw=resp.read(18_000_001)
            if len(raw)>18_000_000:raise ValueError("max_size_exceeded")
            data=json.loads(raw)
            row["http_status"]=resp.status
        bid,ask=data["bids"],data["asks"]
        if not isinstance(data.get("id"),int) or data["id"]<1:raise ValueError("no source update ID")
        stamp=int(data.get("current"))
        if stamp<10**12 or abs(dt.datetime.now(UTC).timestamp()*1000-stamp)>120000:raise ValueError("stale or missing native ms timestamp")
        if len(bid)<20 or len(ask)<20:raise ValueError("insufficient native levels")
        prices_bid=[float(x[0]) for x in bid]
        prices_ask=[float(x[0]) for x in ask]
        if prices_bid!=sorted(prices_bid,reverse=True) or prices_ask!=sorted(prices_ask) or prices_bid[0]>=prices_ask[0]:raise ValueError("unsorted/crossed price book")
        mid=(prices_bid[0]+prices_ask[0])/2
        row.update({"status":"verified","native_update_id":data["id"],
                    "source_timestamp_utc":dt.datetime.fromtimestamp(stamp/1000,UTC).isoformat(),
                    "levels":{"bid":len(bid),"ask":len(ask)},
                    "bid_reach_pct":round((mid-prices_bid[-1])/mid*100,5),
                    "ask_reach_pct":round((prices_ask[-1]-mid)/mid*100,5),
                    "full_1pct":prices_bid[-1]<=mid*.99 and prices_ask[-1]>=mid*1.01,
                    "requested_depth_satisfied":len(bid)>=limit and len(ask)>=limit})
    except urllib.error.HTTPError as e:
        row.update({"status":"http_rejected","http_status":e.code,"reason":e.read(300).decode("utf-8","replace")[:200]})
    except Exception as e:
        row.update({"status":"unverified","reason":str(e)[:160]})
    results[label]=row
p=pathlib.Path("btc-liquidity/data/gate_spot_depth_probe.json")
p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({"checked_utc":dt.datetime.now(UTC).isoformat(),
       "scope":"same official Gate BTC_USDT native spot book; no proxy","requests":results},
       ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:{"status":v["status"],"code":v.get("http_status"),"levels":v.get("levels"),"1pct":v.get("full_1pct")} for k,v in results.items()}))
