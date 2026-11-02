import urllib.request,re
u="https://s3.coinglass.com/v1/cg/_next/static/chunks/pages/pro/onchain/%5Bslug%5D-a758b6efc6d862d6.js"
req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"})
with urllib.request.urlopen(req,timeout=30) as r:
 text=r.read(1900000).decode("utf-8",errors="replace")
print("JS_LENGTH",len(text))
for term in ["onchain","history","metric","chart","fetch(","axios","getChart","api/","series","interval","timeRange"]:
 print("TERM",term,"count",text.lower().count(term.lower()))
 positions=list(re.finditer(re.escape(term),text,re.I))
 for item in positions[:3]:
  at=item.start()
  print("CTX",repr(text[max(0,at-140):at+210])[:400])
