import urllib.request,urllib.error,io,zipfile,json,re
root="https://historical-data.boros.finance/"
for expiry in ("20260327","20260626","20260925","20261225","20270326"):
 url=root+"futures-premium/cme-BTC-"+expiry+".ndjson.zip"
 try:
  with urllib.request.urlopen(url,timeout=24) as r:blob=r.read(2000000)
  with zipfile.ZipFile(io.BytesIO(blob)) as z:
   rows=[json.loads(x) for x in z.read(z.namelist()[0]).splitlines() if x]
  print(expiry,"ROWS",len(rows),"FIRST",rows[0]["datetime"],"LAST",rows[-1]["datetime"],"LATEST_APR",rows[-1]["premiumApr"])
 except Exception as e:print(expiry,"ERROR",str(e)[:100])
try:
 with urllib.request.urlopen(root+"index.html",timeout=15) as r:s=r.read().decode()
 for term in ("manifest","files.json","file-list","index.json","fileTree","fetch("):
  print("INDEX",term,"COUNT",s.count(term),"AROUND",s[max(0,s.find(term)-120):s.find(term)+160] if term in s else "")
except Exception as e:print("INDEX_ERROR",str(e))
