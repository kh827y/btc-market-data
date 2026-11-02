import json, urllib.request, urllib.error, gzip, io
HEAD={"User-Agent":"BTC-research/1.0","Accept":"application/json"}
URLS={
"keyhole_catalog":"https://cryptokeyhole.com/api/v1/catalog?asset=BTC",
"keyhole_metrics":"https://cryptokeyhole.com/api/v1/metrics?asset=BTC",
"keyhole_known":"https://cryptokeyhole.com/api/v1/series?metric=eth.PriceUSD&interval=24h&limit=2",
"keyhole_fear":"https://cryptokeyhole.com/api/v1/fear-and-greed?coin=btc&limit=2",
"official_whale_archive":"https://whale-alert.io/whale-alerts-archive.json.gzip"
}
for label,url in URLS.items():
 try:
  req=urllib.request.Request(url,headers=HEAD)
  with urllib.request.urlopen(req,timeout=35) as response:
   print("SOURCE",label,"HTTP",response.status,"TYPE",response.headers.get("content-type"),"SIZE",response.headers.get("content-length"))
   if label=="official_whale_archive":
    with gzip.GzipFile(fileobj=response) as stream:
     sample=stream.read(22000)
    print("ARCHIVE_HEAD",repr(sample[:2500]))
   else:
    data=json.loads(response.read(6000000))
    if isinstance(data,list):
     print("JSON_LIST",len(data),"SAMPLE",str(data[:3])[:2200])
    elif isinstance(data,dict):
     print("JSON_KEYS",list(data.keys())[:24],"SAMPLE",str(data)[:2700])
 except Exception as e:
  print("SOURCE",label,"ERROR",str(e)[:330])
