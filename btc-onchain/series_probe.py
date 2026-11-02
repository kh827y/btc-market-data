import urllib.request
urls = {
"volume": "https://www.coinglass.com/pro/onchain/bitcoin-whale-exchange-deposit-volume",
"count": "https://www.coinglass.com/pro/onchain/bitcoin-whale-exchange-deposit-count",
"ratio": "https://swisswhaleintelligence.com/glossary/exchange_whale_ratio/"
}
for k,url in urls.items():
 try:
  req = urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"})
  with urllib.request.urlopen(req,timeout=20) as r:
   text = r.read(300000).decode("utf-8",errors="replace")
  print(k,"size",len(text))
  for term in ("2,454.5273","Whale Exchange Deposit Volume","Whale deposits counted","Latest complete day"):
   i=text.find(term)
   print(k,term,"found",i,"sample",text[max(0,i-50):i+160] if i>=0 else "")
 except Exception as e:
  print(k,"FAILED",str(e)[:140])
