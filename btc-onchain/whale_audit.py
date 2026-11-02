import re, urllib.request
url="https://www.coinglass.com/pro/onchain/bitcoin-whale-exchange-deposit-volume"
with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=30) as r:
    html=r.read(320000).decode("utf-8",errors="replace")
scripts=re.findall(r'<script[^>]*src="([^"]+)"',html)
print("SCRIPT_COUNT",len(scripts))
for u in scripts:
    if "onchain" in u.lower() or "pages/" in u.lower() or "chunks/" in u.lower():
        print("SCRIPT",u[:180])
