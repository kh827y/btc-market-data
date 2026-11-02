import urllib.request, re
u="https://www.derivasys.com/research-artifact-license/v1"
try:
 with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"}),timeout=30) as r:html=r.read(350000).decode("utf8",errors="replace")
 txt=re.sub(r'<(script|style)[^>]*>.*?</\\1>',' ',html,flags=re.S|re.I)
 txt=re.sub(r'<[^>]+>',' ',txt)
 txt=re.sub(r'&[^;]{1,12};',' ',txt)
 txt=re.sub(r'\\s+',' ',txt)
 print("LICENSE length",len(txt))
 for word in ("redistribut","commercial","reproduc","research","cache","personal","non-commercial","publish","attribut","derivative"):
  loc=txt.lower().find(word)
  print("TERM",word,loc,"CONTEXT",txt[max(0,loc-260):loc+550] if loc>=0 else "")
 print("BODY",txt[:5000])
except Exception as e:print("LICENSE ERROR",str(e))
