import urllib.request, urllib.error, json
names=["lth_supply_delta_1m","lth_supply_delta_1w","lth_supply","sth_supply","lth_realized_price","sth_realized_price","realized_price","supply_delta_1m","lth_capital","lth_nupl"]
queries={}
for name in names:
 queries[name+"_indexes"]="https://bitview.space/api/series/"+name
 queries[name+"_latest"]="https://bitview.space/api/series/"+name+"/day1/latest"
 queries[name+"_data"]="https://bitview.space/api/series/"+name+"/day1/data?start=2026-10-01&end=2026-10-31"
for key,url in queries.items():
 try:
  req=urllib.request.Request(url,headers={"User-Agent":"BTC-Onchain-Public-Research/1.0","Accept":"application/json"})
  with urllib.request.urlopen(req,timeout=20) as r:
   obj=json.load(r)
   if isinstance(obj,list):v={"type":"list","count":len(obj),"first":obj[:2],"last":obj[-2:]}
   elif isinstance(obj,dict):v={"type":"dict","keys":list(obj.keys())[:30],"first":str(obj)[:1800]}
   else:v={"value":str(obj)[:400]}
   print(key,"OK",str(v)[:2300])
 except Exception as e:print(key,"ERROR",str(e)[:220])
