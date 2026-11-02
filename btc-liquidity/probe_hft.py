"""One-off integration probe: exercise free unauthenticated L2 history endpoints."""
import datetime
import io
import json
import urllib.error
import urllib.parse
import urllib.request
import time

BASE="https://api.cryptohftdata.com/v1"
VENUES=["binance_spot","okx_spot","bybit_spot","binance_futures","okx_futures","kraken_spot"]
for venue in VENUES:
    try:
        query=urllib.parse.urlencode({"exchange":venue,"data_type":"orderbook"})
        with urllib.request.urlopen(urllib.request.Request(BASE+"/symbols?"+query,headers={"User-Agent":"BTC-liquidity-free-source-probe/1.0"}),timeout=20) as response:
            obj=json.load(response)
        syms=obj.get("symbols",[])
        btc=[x for x in syms if x.upper() in ("BTCUSDT","BTC-USDT","XBT/USD","XBTUSD","BTC/USD","BTC-USD","BTC-USDT-SWAP")]
        print("SYMBOL",venue,"matches",btc[:10],"n",len(syms),flush=True)
        if not btc:continue
        symbol=("BTC-USDT" if venue == "okx_spot" else btc[0])
        path=f"{venue}/2026-10-31/12/{symbol}_orderbook.parquet"
        url=BASE+"/download?"+urllib.parse.urlencode({"file":path})
        t=time.monotonic()
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"BTC-liquidity-free-source-probe/1.0","Range":"bytes=0-65535"}),timeout=40) as response:
            data=response.read(65536)
            print("DATA",venue,"status",response.status,"url_domain",urllib.parse.urlparse(response.url).netloc,"size_header",response.headers.get("Content-Length"),"content_range",response.headers.get("Content-Range"),"content_type",response.headers.get("Content-Type"),"first8",data[:8].hex(),"seconds",round(time.monotonic()-t,1),flush=True)
    except Exception as e:
        print("ERROR",venue,type(e).__name__,str(e)[:230],flush=True)
