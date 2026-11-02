import urllib.request,json,datetime as dt,collections
headers={"User-Agent":"BTC-market-research/1.0","Accept":"application/json"}
def get(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=40) as r:return json.load(r)
obj=get("https://www.sharpe.ai/api/futures/data?chart=liquidations&coin=BTC&timeframe=1M")
rows=obj.get("data",[])
by=collections.defaultdict(lambda:{"long":0.0,"short":0.0,"n":0})
cut=dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)
for item in rows:
 if item.get("exchange") not in ("Binance","Bybit"):continue
 t=dt.datetime.fromisoformat(item["timestamp"].replace("Z","+00:00"))
 if t<cut:continue
 side=item.get("side")
 if side not in ("long","short"):continue
 amount=float(item["quantity"])
 by[item["exchange"]][side]+=amount
 by[item["exchange"]]["n"]+=1
print("SHARPE_META",str(obj.get("meta",{}))[:1000])
print("SHARPE_COUNTS_7D",dict(by))
print("SHARPE_FIELDS",rows[0] if rows else {})
print("SHARPE_ROWS",len(rows))
edge=get("https://edgeornot.com/api/liquidations?hours=168&coin=btc")
print("EDGE_BY_EXCHANGE_7D",edge.get("by_exchange"))
