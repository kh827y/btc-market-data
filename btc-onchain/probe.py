"""One-off connectivity + schema probe. Prints public metric samples only, no secrets."""
import json, urllib.request, urllib.error
URLS={
"bg_mvrv":"https://bitcoin-data.com/v1/mvrv?startday=2026-10-25",
"bg_nupl":"https://bitcoin-data.com/v1/nupl?startday=2026-10-25",
"bg_lth_profit":"https://bitcoin-data.com/v1/realized_profit_lth?startday=2026-10-25",
"bg_lth_price":"https://bitcoin-data.com/v1/lth-realized-price/last",
"cm_core":"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur%2CCapRealUSD%2CCapMrktCurUSD&start_time=2026-10-27&frequency=1d&page_size=4",
"cm_exchange":"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=SplyExNtv%2CFlowInExNtv%2CFlowOutExNtv&start_time=2026-10-29&frequency=1d&page_size=3"}
for key,url in URLS.items():
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"BTC-Onchain-Research/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=25) as response:
            raw=response.read(200000)
            try:
                val=json.loads(raw)
                if isinstance(val,list):
                    print(key,"200 list",len(val),"head",str(val[:2])[:1400],"tail",str(val[-1:])[:900])
                elif isinstance(val,dict):
                    print(key,"200 dict keys",list(val.keys()),"head",str(val.get("data",val))[:1700])
                else: print(key,"200 other",str(val)[:500])
            except Exception as e:print(key,"200 not json",str(e),raw[:500])
    except Exception as e:
        print(key,"ERROR",str(e)[:500])
