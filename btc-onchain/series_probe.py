import urllib.request,re
for suffix in ("bitcoin-whale-exchange-deposit-volume","bitcoin-whale-exchange-deposit-count"):
 u="https://www.coinglass.com/pro/onchain/"+suffix
 req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"})
 with urllib.request.urlopen(req,timeout=22) as r:content=r.read(250000).decode("utf-8")
 for word in ("KpiStrip_sub","1D change","7D change","30D change"):
  k=content.find(word)
  print(suffix,word,repr(content[max(0,k-150):k+200])[:450])
