import json,urllib.request,datetime as dt
urls={
"funding_history_binance":"https://www.sharpe.ai/api/funding/rates?type=history&coin=BTC&exchange=binance&days=30&limit=300",
"funding_history_bybit":"https://www.sharpe.ai/api/funding/rates?type=history&coin=BTC&exchange=bybit&days=30&limit=300",
"funding_history_okx":"https://www.sharpe.ai/api/funding/rates?type=history&coin=BTC&exchange=okx&days=30&limit=300",
"funding_chart":"https://www.sharpe.ai/api/futures/data?chart=funding-rate&coin=BTC&timeframe=1W&exchanges=binance%2Cbybit%2Cokx",
"oi_stacked":"https://www.sharpe.ai/api/futures/data?chart=oi-stacked&coin=BTC&timeframe=1M",
"basis_term":"https://www.sharpe.ai/api/futures/data?chart=term-structure&coin=BTC&timeframe=1W",
"basis_curve":"https://www.sharpe.ai/api/futures/data?chart=annualized-basis&coin=BTC&timeframe=1W",
"cftc_4y":"https://publicreporting.cftc.gov/resource/gpe5-46if.json?$where=cftc_contract_market_code%3D%27133741%27%20and%20report_date_as_yyyy_mm_dd%20%3E%3D%20%272022-01-01%27&$limit=350&$order=report_date_as_yyyy_mm_dd%20DESC"
}
for k,u in urls.items():
 try:
  req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0 BTC research","Accept":"application/json"})
  with urllib.request.urlopen(req,timeout=25) as response: obj=json.load(response)
  if isinstance(obj,list):print(k,"OK list",len(obj),"first",str(obj[:1])[:560],"last",str(obj[-1:])[:450])
  else:
   data=obj.get("data",[])
   print(k,"OK keys",list(obj)[:18],"n",len(data) if isinstance(data,list) else type(data).__name__,"first",str(data[:2])[:700] if isinstance(data,list) else str(data)[:400],"last",str(data[-2:])[:500] if isinstance(data,list) else "","meta",str(obj.get("meta",obj.get("coverage",obj.get("pagination",{}))))[:800])
 except Exception as e:print(k,"ERROR",str(e)[:230])
