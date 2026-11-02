"""Investigate freely exposed chart data without assuming source availability."""
import urllib.request, json, re
url="https://www.coinglass.com/pro/onchain/bitcoin-whale-exchange-deposit-volume"
req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"})
with urllib.request.urlopen(req,timeout=30) as response:
    raw=response.read(500000).decode("utf-8",errors="replace")
for key in ('"dataPoints"','"historical"','"series"','__NEXT_DATA__','download','"chart"','"values"','"dates"'):
    print(key,raw.count(key))
    idx=raw.find(key)
    if idx>=0:print("CONTEXT",repr(raw[max(0,idx-100):idx+290]))
start=raw.find('<script id="__NEXT_DATA__"')
if start>=0:
    end=raw.find('</script>',start)
    chunk=raw[raw.find('>',start)+1:end]
    try:
        obj=json.loads(chunk)
        print("NEXT-KEYS",list(obj))
        print("NEXT-SIZE",len(chunk))
        txt=json.dumps(obj)
        for key in ('dataPoints','chart','volume','series','latest'):
            pos=txt.find(key);print("NEXT",key,pos,txt[max(0,pos-100):pos+230] if pos>=0 else "")
    except Exception as e:print("NEXT-PARSE-ERROR",str(e)[:200])
