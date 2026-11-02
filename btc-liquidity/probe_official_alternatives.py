"""One-shot verification of *official* alternative live BTC order-book transports.

Runs in the same GitHub-hosted environment as the production collectors. An
HTTP 403/451 is recorded as an access restriction, not a reason for proxying
or routing through a different jurisdiction. Only an actual validated market
snapshot can mark an exchange usable.
"""
import datetime as dt
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from websocket import create_connection, WebSocketTimeoutException, WebSocketBadStatusException

UTC=dt.timezone.utc
TIMEOUT=9
REST={
 "bybit_spot_primary": "https://api.bybit.com/v5/market/orderbook?category=spot&symbol=BTCUSDT&limit=200",
 "bybit_spot_official_second_domain": "https://api.bytick.com/v5/market/orderbook?category=spot&symbol=BTCUSDT&limit=200",
 "bybit_perp_official_second_domain": "https://api.bytick.com/v5/market/orderbook?category=linear&symbol=BTCUSDT&limit=200",
 "binance_usdm_fapi": "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=100",
}
WS={
 "bybit_spot_official_ws": {
   "url":"wss://stream.bybit.com/v5/public/spot",
   "message":{"op":"subscribe","args":["orderbook.200.BTCUSDT"]},
   "topic":"orderbook.200.BTCUSDT","market":"spot"},
 "bybit_perp_official_ws": {
   "url":"wss://stream.bybit.com/v5/public/linear",
   "message":{"op":"subscribe","args":["orderbook.200.BTCUSDT"]},
   "topic":"orderbook.200.BTCUSDT","market":"perpetual"},
 "binance_usdm_official_partial_ws": {
   "url":"wss://fstream.binance.com/ws/btcusdt@depth20@100ms",
   "market":"perpetual"},
}
def validate_book(bids,asks,source_ms=None):
    import sys
    sys.path.insert(0,"btc-liquidity")
    from collector import summarize_orderbook
    if source_ms is not None:
        age_ms=dt.datetime.now(UTC).timestamp()*1000-int(source_ms)
        if not -10000 <= age_ms <= 120000:
            raise ValueError("source timestamp stale or in future")
    data=summarize_orderbook(bids,asks)
    return {"verified":True,"levels":data["levels"],"mid_usd":data["mid_usd"],
            "complete_bands":[k for k,v in data["bands"].items()
                              if v["bid_coverage_complete"] and v["ask_coverage_complete"]],
            "bid_ask_ordering_valid":True,
            "source_time_valid":source_ms is not None}
def rest_probe(name,url):
    t0=time.monotonic()
    req=urllib.request.Request(url,headers={"User-Agent":"BTC-live-depth-integrity-check/1.0",
                                             "Accept":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=TIMEOUT) as resp:
            data=json.loads(resp.read(4000000))
        if name.startswith("bybit"):
            if data.get("retCode")!=0:raise ValueError("Bybit API result retCode not zero")
            a=data["result"]
            valid=validate_book(a["b"],a["a"],a["ts"])
        else:
            valid=validate_book(data["bids"],data["asks"],data.get("E"))
        return {"status":"verified","transport":"official_rest","elapsed_s":round(time.monotonic()-t0,2),**valid}
    except urllib.error.HTTPError as e:
        return {"status":"blocked" if e.code in (403,451) else "http_error",
                "http_status":e.code,"reason":str(e.reason)[:120],
                "elapsed_s":round(time.monotonic()-t0,2)}
    except Exception as e:
        return {"status":"error","error":str(e)[:170],
                "elapsed_s":round(time.monotonic()-t0,2)}
def ws_probe(name,item):
    t0=time.monotonic()
    url=item["url"]
    connection=None
    try:
        connection=create_connection(url,timeout=TIMEOUT,enable_multithread=False)
        if item.get("message"): connection.send(json.dumps(item["message"]))
        for attempt in range(8):
            msg=json.loads(connection.recv())
            if name.startswith("bybit"):
                if msg.get("topic")!=item["topic"] or msg.get("type")!="snapshot":
                    continue
                book=msg["data"]
                valid=validate_book(book["b"],book["a"],msg.get("ts"))
                return {"status":"verified","transport":"official_websocket_snapshot",
                        "market":item["market"],"url":url,"elapsed_s":round(time.monotonic()-t0,2),
                        **valid}
            if "data" in msg and isinstance(msg["data"],dict):msg=msg["data"]
            if msg.get("e") not in ("depthUpdate","partialDepthUpdate") and not (
                "bids" in msg and "asks" in msg):
                continue
            if msg.get("bids") and msg.get("asks"):
                valid=validate_book(msg["bids"],msg["asks"],msg.get("E"))
                return {"status":"verified","transport":"official_websocket_partial_depth",
                        "market":item["market"],"url":url,"elapsed_s":round(time.monotonic()-t0,2),
                        **valid}
        raise ValueError("No order book snapshot after 8 frames")
    except Exception as e:
        err=str(e)[:240]
        return {"status":"blocked" if "403" in err or "451" in err else "error",
                "transport":"websocket","url":url,"error":err,
                "elapsed_s":round(time.monotonic()-t0,2)}
    finally:
        if connection:
            try: connection.close()
            except Exception: pass
def main():
    result={"checked_utc":dt.datetime.now(UTC).isoformat(),
            "scope":"GitHub-hosted runner; official matching market only; no regional proxies",
            "tests":{}}
    for name,url in REST.items():
        x=rest_probe(name,url);result["tests"][name]=x
        print("REST",name,x,flush=True)
    for name,item in WS.items():
        x=ws_probe(name,item);result["tests"][name]=x
        print("WS",name,x,flush=True)
    result["finished_utc"]=dt.datetime.now(UTC).isoformat()
    result["verified_official_alternatives"]=[k for k,v in result["tests"].items()
                                             if v.get("status")=="verified"]
    result["restricted_or_failed"]=[k for k,v in result["tests"].items()
                                   if v.get("status")!="verified"]
    p=Path("btc-liquidity/data/official_alt_probe.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("SUMMARY",json.dumps({"checked":result["checked_utc"],"verified":result["verified_official_alternatives"],"failed":result["restricted_or_failed"]}),flush=True)
if __name__=="__main__":main()
