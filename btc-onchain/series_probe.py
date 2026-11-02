import json,urllib.request,urllib.error,csv,io
urls={
 "bitview_lth_search":"https://bitview.space/api/series/search?q=lth",
 "bitview_supply_search":"https://bitview.space/api/series/search?q=supply",
 "bitview_realized_search":"https://bitview.space/api/series/search?q=realized",
 "bitview_catalog":"https://bitview.space/api/series/list",
 "explore21_hodl":"https://charts.explore21.com/data/bitcoin-hodl-waves.csv",
 "explore21_realized":"https://charts.explore21.com/data/bitcoin-realized-price.csv",
 "researchbitcoin_demo":"https://api.researchbitcoin.net/v2/supply_distribution",
}
for k,u in urls.items():
 try:
  req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0 (BTC onchain public research)","Accept":"application/json,text/csv,*/*"})
  with urllib.request.urlopen(req,timeout=22) as r:
   raw=r.read(450000);ct=r.headers.get("content-type","")
   try:
    d=json.loads(raw)
    if isinstance(d,list):
     def summarize(x):
      if isinstance(x,dict):return {name:str(value)[:110] for name,value in list(x.items())[:8]}
      return str(x)[:140]
     display={"type":"list","n_partial":len(d),"head":[summarize(x) for x in d[:5]],"tail":[summarize(x) for x in d[-2:]]}
    elif isinstance(d,dict):
     display={"type":"dict","keys":list(d)[:20],"top":str(d)[:1200]}
    else:display=str(d)[:500]
   except:
    rows=raw.decode("utf-8",errors="replace").splitlines()
    display={"first_lines":rows[:2],"last_lines":rows[-2:],"bytes_read":len(raw),"last_complete_line":raw.endswith(b"\n")}
   print(k,"OK",r.status,ct,str(display)[:2400])
 except Exception as e:print(k,"ERROR",str(e)[:350])
