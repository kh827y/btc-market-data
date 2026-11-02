import json, urllib.request,collections
u="https://www.sharpe.ai/api/futures/data?chart=oi-stacked&coin=BTC&timeframe=1M"
with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"BTC research","Accept":"application/json"}),timeout=45) as r: data=json.load(r)
rows=data["data"]
venues=collections.Counter(x.get("exchange") for x in rows)
print("VENUES",sorted(venues.items()))
for venue,n in sorted(venues.items()):
 r=sorted([x for x in rows if x.get("exchange")==venue],key=lambda x:x["timestamp"])
 print("VENUE",venue,"N",n,"FIRST",r[0]["timestamp"],"LAST",r[-1]["timestamp"],"VALUED",r[-1].get("open_interest_value"))
print("PROVIDER_META",str(data.get("meta"))[:1000])
