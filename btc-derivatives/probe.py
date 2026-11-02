"""One-time direct API read probe for BTC derivatives sources; no credentials."""
import json,urllib.request,urllib.error,datetime as dt
URLS={
"edge_liq":"https://edgeornot.com/api/liquidations?hours=48&coin=btc",
"edge_oi30":"https://edgeornot.com/api/oi/btc?days=30",
"edge_exchanges":"https://edgeornot.com/api/oi-by-exchange",
"sharpe_oi":"https://www.sharpe.ai/api/futures/data?chart=oi-snapshot&coin=BTC&timeframe=1M",
"sharpe_funding":"https://www.sharpe.ai/api/futures/data?chart=funding-rate&coin=BTC&timeframe=1M",
"sharpe_liq":"https://www.sharpe.ai/api/futures/data?chart=liquidations&coin=BTC&timeframe=1M",
"sharpe_basis":"https://www.sharpe.ai/api/futures/data?chart=annualized-basis&coin=BTC&timeframe=1M",
"binance_oi":"https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=35",
"binance_fund":"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=6",
"bybit_oi":"https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=1d&limit=12",
"bybit_fund":"https://api.bybit.com/v5/market/funding/history?category=linear&symbol=BTCUSDT&limit=7",
"okx_oi":"https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history?ccy=BTC&period=1D",
"okx_fund":"https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=7",
"cftc_btc":"https://publicreporting.cftc.gov/resource/gpe5-46if.json?$where=cftc_contract_market_code%3D%27133741%27&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=3"
}
for k,u in URLS.items():
 try:
  request=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0 BTC derivatives historical research","Accept":"application/json"})
  with urllib.request.urlopen(request,timeout=17) as response:
   buf=response.read(400000);obj=json.loads(buf)
  if isinstance(obj,list):
   print(k,"OK list",len(obj),"first",repr(obj[:1])[:1150],"last",repr(obj[-1:])[:900])
  elif isinstance(obj,dict):
   print(k,"OK dict keys",list(obj)[:22],"sample",repr(obj)[:1600])
  else:print(k,"OK type",type(obj).__name__)
 except Exception as e:print(k,"ERROR",type(e).__name__,str(e)[:250])
