import urllib.request,json,urllib.error
HEAD={"User-Agent":"BTC-research/1.0","Accept":"application/json"}
def get(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=55) as r:return json.load(r)
obj=get("https://cryptokeyhole.com/api/v1/catalog?asset=BTC")
hits=[]
for v in obj.get("metrics",[]):
 name=v.get("name",""); ident=v.get("id",""); desc=v.get("description","")
 if "whale" in name.lower() and ("exchange" in name.lower() or "deposit" in name.lower()):
  hits.append(v)
 if ("whale" in ident.lower() and ("exchange" in ident.lower() or "deposit" in ident.lower())) and v not in hits:
  hits.append(v)
print("MATCHES",len(hits))
for h in hits[:45]:
 print("CAT",json.dumps({k:h.get(k) for k in ["id","name","status","access","plan","family","historyStart","historyEnd","intervals","reason"]},ensure_ascii=False)[:600])
for h in hits[:15]:
 metric=h.get("id")
 try:
  result=get("https://cryptokeyhole.com/api/v1/series?metric="+metric+"&interval=24h&limit=16")
  print("FETCH",metric,"keys",list(result)[:16],"npoints",len(result.get("points",[])),"last",str(result.get("points",[])[-1:])[:500],"error",result.get("error"))
 except urllib.error.HTTPError as e:
  print("FETCH_ERR",metric,e.code,e.read(320).decode("utf8",errors="replace"))
 except Exception as e:
  print("FETCH_ERR",metric,str(e)[:220])
