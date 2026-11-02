"""BTC option risk monitoring from live Deribit chain and Derivasys research comparisons."""
import datetime as dt
import json
import math
import pathlib
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-options/data")
DERIBIT="https://www.deribit.com/api/v2/public/"
RESEARCH="https://api.derivasys.com/api/v1/data/BTC"
TENORS={"1W":7,"2W":14,"1M":30,"3M":90,"6M":180}
def get(url):
    request=urllib.request.Request(url,headers={"User-Agent":"BTC-options-monitor/1.0","Accept":"application/json"})
    with urllib.request.urlopen(request,timeout=45) as response:
        return json.load(response)
def fetch_deribit(method,query):
    params=urllib.parse.urlencode(query)
    result=get(DERIBIT+method+"?"+params)
    if "error" in result or "result" not in result:
        raise ValueError("Deribit "+method+": "+str(result.get("error")))
    return result["result"]
def norm_cdf(x):
    return 0.5*(1+math.erf(x/math.sqrt(2)))
def delta_forward(fwd,strike,iv,tau,kind):
    sigma=iv/100
    if fwd<=0 or strike<=0 or sigma<=0 or tau<=0:
        raise ValueError("invalid option greeks inputs")
    d1=(math.log(fwd/strike)+0.5*sigma*sigma*tau)/(sigma*math.sqrt(tau))
    return norm_cdf(d1) if kind=="C" else norm_cdf(d1)-1
def iso_epoch(ts):
    return dt.datetime.fromtimestamp(ts/1000,UTC).isoformat()
def quote_ok(v):
    try:
        return v is not None and math.isfinite(float(v)) and float(v)>0
    except (ValueError,TypeError): return False
