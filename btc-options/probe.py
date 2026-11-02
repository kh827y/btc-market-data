"""Public BTC options history API verification (no keys)."""
import json,urllib.request,urllib.error,datetime as dt
urls={
"catalog":"https://api.derivasys.com/api/v1/data/catalog",
"dates":"https://api.derivasys.com/api/v1/data/BTC/dates",
"latest":"https://api.derivasys.com/api/v1/data/BTC/latest",
"history":"https://api.derivasys.com/api/v1/data/BTC/observations?start=2026-10-20&end=2026-11-02&limit=13",
"deribit_dvol":"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp=1790899200000&end_timestamp=1793577600000&resolution=1D",
"deribit_chain":"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
}
for label,url in urls.items():
 try:
  req=urllib.request.Request(url,headers={"User-Agent":"BTC-options-research/1.0","Accept":"application/json"})
  with urllib.request.urlopen(req,timeout=28) as resp:
   data=json.load(resp)
   print("META",label,resp.status,"cache",resp.headers.get("X-Data-As-Of"))
  if label=="dates":
   arr=data if isinstance(data,list) else next((v for v in data.values() if isinstance(v,list)),[])
   print("DATA",label,"type",type(data).__name__,"keys",list(data)[:10] if isinstance(data,dict) else [],"len",len(arr),"first",str(arr[:4])[:500],"last",str(arr[-4:])[:500])
  elif label=="latest":
   print("DATA",label,json.dumps(data,ensure_ascii=False)[:5400])
  elif label=="history":
   print("DATA",label,"keys",list(data)[:30],"returned",data.get("returnedCount"),"total",data.get("totalAvailable"),"more",data.get("hasMore"),"first",json.dumps(data.get("observations",[])[:1])[:1700],"last",json.dumps(data.get("observations",[])[-1:])[:1500])
  elif label=="catalog":
   print("DATA",label,json.dumps(data,ensure_ascii=False)[:3500])
  elif label=="deribit_dvol":
   print("DATA",label,"keys",list(data)[:15],"result",str(data.get("result"))[:1600])
  elif label=="deribit_chain":
   arr=data.get("result",[])
   print("DATA",label,"count",len(arr),"first",str(arr[:1])[:650])
 except Exception as e:print("ERROR",label,type(e).__name__,str(e)[:350])
