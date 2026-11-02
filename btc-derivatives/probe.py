import urllib.request,urllib.error,zipfile,io,re
urls=[
"https://historical-data.boros.finance/futures-premium/cme-BTC-20260626.ndjson.zip",
"https://historical-data.boros.finance/data/futures-premium/cme-BTC-20260626.ndjson.zip",
"https://historical-data.boros.finance/api/files?path=futures-premium",
"https://historical-data.boros.finance/index.html"]
for u in urls:
 try:
  with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"BTC-research/1.0"}),timeout=22) as r:
   ct=r.headers.get("content-type");data=r.read(3000000);url=r.url
  print("URL",u,"OK",ct,len(data),"location",url)
  if zipfile.is_zipfile(io.BytesIO(data)):
   with zipfile.ZipFile(io.BytesIO(data)) as z:
    print("ZIP FILES",z.namelist()[:5])
    for p in z.namelist()[:1]:
     rows=z.read(p).decode("utf-8",errors="replace").splitlines()
     print("ZIP ROWS",len(rows),"first",rows[:1],"last",rows[-1:])
  elif ct and "html" in ct:
   html=data.decode("utf8",errors="replace")
   print("LINKS",re.findall(r'<script[^>]+src="([^"]+)"',html)[-7:])
   print("MATCH",re.findall(r'[^"]{0,100}cme-BTC-20260626[^"]{0,100}',html)[:2])
  else:print("HEAD",repr(data[:500]))
 except Exception as e:print("URL",u,"ERROR",str(e)[:160])
