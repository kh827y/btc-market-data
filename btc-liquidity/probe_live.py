"""Verify actual free public BTC order-book APIs inside GitHub Actions.
This does NOT fabricate unavailable venues or claim full depth on shallow books.
"""
import datetime as dt
import json
import traceback
from pathlib import Path
from collector import VENUES,fetch,normalize_book,summarize_orderbook,gate_btc_contract_size,okx_swap_contract_size,UTC

def run():
    now=dt.datetime.now(UTC)
    checks={}
    for name,(market,symbol,url) in VENUES.items():
        try:
            raw=fetch(url)
            bids,asks,source_ms=normalize_book(name,raw)
            multiplier=1.0
            if name=="gate_usdt_perp":
                multiplier=gate_btc_contract_size(fetch("https://api.gateio.ws/api/v4/futures/usdt/contracts/BTC_USDT"))
            elif name=="okx_usdt_perp":
                multiplier=okx_swap_contract_size(fetch("https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP"))
            if multiplier!=1:
                bids=[[x[0],str(float(x[1])*multiplier)] for x in bids]
                asks=[[x[0],str(float(x[1])*multiplier)] for x in asks]
            if source_ms is not None and abs(dt.datetime.now(UTC).timestamp()*1000-source_ms)>120000:
                raise ValueError("stale source timestamp")
            result=summarize_orderbook(bids,asks)
            complete_bands=[band for band,d in result["bands"].items()
                            if d["bid_coverage_complete"] and d["ask_coverage_complete"]]
            checks[name]={"status":"ok","usable":bool(complete_bands),"market":market,"symbol":symbol,
                          "mid_usd":result["mid_usd"],
                          "level_count":result["levels"],
                          "complete_bands":complete_bands,
                          "captured_at_utc":dt.datetime.now(UTC).isoformat(),
                          "contract_size_btc":multiplier if multiplier!=1 else None,
                          "source_time_utc":dt.datetime.fromtimestamp(source_ms/1000,UTC).isoformat() if source_ms else None}
        except Exception as exc:
            checks[name]={"status":"error","market":market,
                          "error":str(exc)[:250]}
    output={"tested_utc":now.isoformat(),"finished_utc":dt.datetime.now(UTC).isoformat(),
            "tested_endpoints":len(VENUES),
            "working":sum(v["status"]=="ok" for v in checks.values()),
            "spot_usable":sum(v.get("usable",False) for v in checks.values() if v["market"]=="spot"),
            "perpetual_usable":sum(v.get("usable",False) for v in checks.values() if v["market"]=="perpetual"),
            "markets":checks}
    dest=Path("btc-liquidity/data/live_probe.json")
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps(output,ensure_ascii=False))
if __name__=="__main__":run()
