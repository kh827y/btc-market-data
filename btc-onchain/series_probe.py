import json,urllib.request
base="https://bitview.space/api/series/lth_supply/day1/data?"
for a,b in [("2026-10-31","2026-11-02"),("2026-10-30","2026-11-02"),("2022-11-01","2026-11-02")]:
 try:
  with urllib.request.urlopen(base+"start="+a+"&end="+b,timeout=35) as r:
   v=json.load(r)
   print(a,b,len(v),v[:2],v[-2:])
 except Exception as e:
  print(a,b,str(e))
