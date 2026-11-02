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

def interpolate(sorted_nodes,target):
    nodes=sorted((float(d),float(iv)) for d,iv in sorted_nodes if math.isfinite(float(d)) and quote_ok(iv))
    if len(nodes)<2:return None
    for (da,va),(db,vb) in zip(nodes,nodes[1:]):
        if da<=target<=db and db-da>1e-8:
            if db-da>0.2:return None
            return va+(vb-va)*(target-da)/(db-da)
    return None

def expiry_surface(instruments,summaries,now):
    indexes={item["instrument_name"]:item for item in summaries}
    groups=defaultdict(lambda:{"C":[],"P":[],"atm":[]})
    for ins in instruments:
        record=indexes.get(ins.get("instrument_name"))
        if not record:continue
        try:
            expiry=dt.datetime.fromtimestamp(int(ins["expiration_timestamp"])/1000,UTC)
            tau=(expiry-now).total_seconds()/86400/365
            days=tau*365
            if days<3 or days>400:continue
            kind="C" if ins["option_type"]=="call" else "P"
            strike=float(ins["strike"])
            forward=float(record["underlying_price"])
            iv=float(record["mark_iv"])
            if not 5<=iv<=300 or not quote_ok(record.get("ask_price")):
                continue
            oi=float(record.get("open_interest") or 0)
            if oi<=0:continue
            delta=delta_forward(forward,strike,iv,tau,kind)
            if kind=="C":
                if delta>0.7 or delta<0.02:continue
                coord=delta
            else:
                if delta<-0.7 or delta>-0.02:continue
                coord=-delta
            key=expiry.isoformat()
            groups[key][kind].append((coord,iv))
            if abs(math.log(strike/forward))<0.07:
                groups[key]["atm"].append((math.log(strike/forward),iv))
            groups[key]["days"]=days
            groups[key]["expiry"]=key
        except (KeyError,ValueError,TypeError,OverflowError):
            continue
    surfaces={}
    for expiry,rows in groups.items():
        call_iv=interpolate(rows["C"],0.25)
        put_iv=interpolate(rows["P"],0.25)
        # At-the-forward IV from local moneyness smile around m=0.
        atm_iv=interpolate(rows["atm"],0.0)
        if any(v is None for v in (call_iv,put_iv,atm_iv)):
            continue
        days=rows["days"]
        surfaces[expiry]={"expiration":expiry,"days":round(days,3),
            "atm_iv_pct":round(atm_iv,4),
            "call25_iv_pct":round(call_iv,4),"put25_iv_pct":round(put_iv,4),
            "rr25_call_minus_put_volpts":round(call_iv-put_iv,4),
            "bf25_wings_minus_atm_volpts":round((call_iv+put_iv)/2-atm_iv,4),
            "observed_strikes":{"call":len(rows["C"]),"put":len(rows["P"]),"atm":len(rows["atm"])}}
    return surfaces

def fixed_tenor(surfaces,days_target):
    arr=sorted(surfaces.values(),key=lambda row:row["days"])
    # Never extrapolate a 30d claim beyond listed expiry coverage.
    before=[row for row in arr if row["days"]<=days_target]
    after=[row for row in arr if row["days"]>=days_target]
    if not before or not after:return {"status":"unavailable","reason":"tenor outside observed maturities"}
    left=before[-1];right=after[0]
    if right["days"]-left["days"]>50:
        return {"status":"unavailable","reason":"expiry interpolation gap >50 days"}
    if left["days"]==right["days"]:
        values={key:left[key] for key in ("atm_iv_pct","call25_iv_pct","put25_iv_pct")}
    else:
        w=(days_target-left["days"])/(right["days"]-left["days"])
        # Interpolate each wing's total variance by maturity (not IV linearly).
        values={}
        for key in ("atm_iv_pct","call25_iv_pct","put25_iv_pct"):
            v1=(left[key]/100)**2*left["days"]/365
            v2=(right[key]/100)**2*right["days"]/365
            vol=math.sqrt(max(0,((1-w)*v1+w*v2)*365/days_target))*100
            values[key]=round(vol,4)
    values.update({"status":"available","target_days":days_target,
                   "expiry_left":left["expiration"],"expiry_right":right["expiration"],
                   "rr25_call_minus_put_volpts":round(values["call25_iv_pct"]-values["put25_iv_pct"],4),
                   "bf25_volpts":round((values["call25_iv_pct"]+values["put25_iv_pct"])/2-values["atm_iv_pct"],4),
                   "method":"variance-time interpolation of 25d option mark IV and ATM; forward delta approximated analytically"})
    return values

def fetch_chain(now):
    instruments=fetch_deribit("get_instruments",{"currency":"BTC","kind":"option","expired":"false"})
    quotes=fetch_deribit("get_book_summary_by_currency",{"currency":"BTC","kind":"option"})
    if len(instruments)<150 or len(quotes)<150:
        raise ValueError("incomplete Deribit option chain")
    surfaces=expiry_surface(instruments,quotes,now)
    if len(surfaces)<2:raise ValueError("fewer than 2 valid volatility expiries")
    tenors={k:fixed_tenor(surfaces,d) for k,d in TENORS.items()}
    return {"as_of_utc":now.isoformat(),"raw_instruments_count":len(instruments),
            "quoted_instruments_count":len(quotes),
            "valid_expiries":len(surfaces),
            "term_structure":tenors,
            "expiries":surfaces,
            "venue":"Deribit","sample_type":"mark_IV, non-executable reference, not bid/ask",
            "rr_convention":"25delta call IV - 25delta put IV (negative=put premium)",
            "formula":"Black forward-delta approximation, interpolation to 25d and forward ATM; source delta convention may differ",
            "quality_limit":"Not a calibrated professional SVI surface; spread/illiquidity can distort nearest strikes."}
