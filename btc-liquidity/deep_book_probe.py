"""One-off native full-depth BTC REST probe on GitHub Actions network.

Only official live-public endpoints; no mirrors/proxies/testnets. Does NOT
replace existing validated 11/11 collector unless the SAME instrument and
both sides of a genuinely newer native full snapshot pass strict checks.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
import urllib.request
import urllib.error

UTC=dt.timezone.utc
NOW=dt.datetime.now(UTC)
TARGETS={
 "bybit_spot_full":(
   "https://api.bybit.com/v5/market/full_orderbook?category=spot&symbol=BTCUSDT",
   "bybit_spot"),
 "bybit_usdt_perp_full":(
   "https://api.bybit.com/v5/market/full_orderbook?category=linear&symbol=BTCUSDT",
   "bybit_usdt_perp"),
 "gate_usdt_perp_500":(
   "https://api.gateio.ws/api/v4/futures/usdt/order_book?contract=BTC_USDT&limit=500&with_id=true",
   "gate_usdt_perp"),
}
def validate_sides(bids,asks):
    def check(rows,sign):
        if not isinstance(rows,list) or len(rows)<10:raise ValueError("insufficient_depth")
        p=[]
        for row in rows:
            price=float(row["p"] if isinstance(row,dict) else row[0])
            qty=float(abs(row["s"]) if isinstance(row,dict) else row[1])
            if not all(math.isfinite(x) and x>0 for x in (price,qty)):
                raise ValueError("nonpositive_or_nonfinite_book_size")
            p.append(price)
        if any((a<=b if sign==1 else a>=b) for a,b in zip(p,p[1:])):
            raise ValueError("wrong_price_sort_order")
        return p
    bid_prices=check(bids,1)
    ask_prices=check(asks,-1)
    if bid_prices[0]>=ask_prices[0]:raise ValueError("crossed_spread")
    mid=(bid_prices[0]+ask_prices[0])/2
    return {"bid_count":len(bids),"ask_count":len(asks),
            "bid_reach_pct":round((mid-bid_prices[-1])/mid*100,5),
            "ask_reach_pct":round((ask_prices[-1]-mid)/mid*100,5),
            "bid_1pct_complete":bid_prices[-1]<=mid*0.99,
            "ask_1pct_complete":ask_prices[-1]>=mid*1.01}

def fetch(url):
    req=urllib.request.Request(url,headers={
       "User-Agent":"BTC-market-depth-provenance-audit/1.0",
       "Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=16) as response:
        body=response.read(4_000_001)
        if len(body)>4_000_000:raise ValueError("response_too_large")
        return json.loads(body)

def probe(name,url,venue):
    now=dt.datetime.now(UTC)
    out={"venue":venue,"official_url":url,"checked_at_utc":now.isoformat(),
         "status":"unavailable","not_substitutable_with_other_market":True}
    try:
        doc=fetch(url)
        if name.startswith("bybit"):
            if not isinstance(doc,dict) or doc.get("retCode")!=0:
                raise ValueError("official_bybit_nonzero_retcode:"+str(doc.get("retCode")))
            d=doc.get("result") or {}
            if d.get("s")!="BTCUSDT":raise ValueError("wrong_symbol")
            if not isinstance(d.get("u"),int) or not isinstance(d.get("seq"),int):
                raise ValueError("missing_exchange_sequence")
            stamp=doc.get("time") or d.get("ts")
            timestamp=dt.datetime.fromtimestamp(int(d.get("ts"))/1000,UTC)
            bids,asks=d.get("b"),d.get("a")
            out.update({"exchange_update_id":d["u"],"exchange_sequence":d["seq"],
                        "observed_at_utc":timestamp.isoformat()})
        else:
            if not isinstance(doc,dict):raise ValueError("invalid_gate_response")
            if not isinstance(doc.get("id"),int):raise ValueError("missing_gate_orderbook_id")
            if not isinstance(doc.get("current"),(int,float)):
                raise ValueError("missing_gate_source_time")
            timestamp=dt.datetime.fromtimestamp(float(doc["current"]),UTC)
            bids,asks=doc.get("bids"),doc.get("asks")
            out.update({"exchange_update_id":doc["id"],
                        "observed_at_utc":timestamp.isoformat()})
        age=(dt.datetime.now(UTC)-timestamp).total_seconds()
        if age < -10 or age > 120:raise ValueError("stale_or_future_exchange_timestamp")
        out.update(validate_sides(bids,asks))
        out["status"]="verified_native_full_snapshot"
        out["capture_source_time_lag_seconds"]=round(age,3)
        out["can_recover_1pct"]=out["bid_1pct_complete"] and out["ask_1pct_complete"]
    except Exception as exc:
        out["reason"]=str(exc)[:180]
        if isinstance(exc,urllib.error.HTTPError):
            out["server_error_excerpt"]=exc.read(900).decode("utf-8","replace")[:900]
        out["http_error_code"]=exc.code if isinstance(exc,urllib.error.HTTPError) else None
    return out

def main():
    checks={k:probe(k,url,venue) for k,(url,venue) in TARGETS.items()}
    payload={"probe_at_utc":dt.datetime.now(UTC).isoformat(),"kind":"official_native_book_depth_one_off_probe",
       "scope":"same real venue/instrument only; not replacements; no proxy/no mirror",
       "markets":checks,
       "all_verified":all(v["status"]=="verified_native_full_snapshot" for v in checks.values()),
       "bybit_1pct_verified":all(v.get("can_recover_1pct") is True for k,v in checks.items() if k.startswith("bybit")),
       "gate_1pct_verified":checks["gate_usdt_perp_500"].get("can_recover_1pct") is True}
    dst=Path("btc-liquidity/data/deep_book_probe.json")
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print(json.dumps(payload,ensure_ascii=False))
if __name__=="__main__":main()
