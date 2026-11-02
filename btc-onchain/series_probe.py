import urllib.request,re
url="https://www.coinglass.com/pro/onchain/bitcoin-whale-exchange-deposit-volume"
req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"})
with urllib.request.urlopen(req,timeout=25) as r:s=r.read(500000).decode("utf-8")
print("HTML bytes",len(s))
for v in ("2011-08-19","2026-10-24","2026-10-30","2026-10-31","chartData","seriesData","dataPoints","timeSeries","__NEXT_DATA__","application/json","download","hourly"):
 print(v,"count",s.count(v),"first",s.find(v))
for pat in (r'20\d\d-\d\d-\d\d',r'179\d{7}'):
 print(pat,"matching",len(re.findall(pat,s)))
