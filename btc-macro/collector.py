"""Free, source-qualified BTC macro and US spot Bitcoin ETF risk inputs.

FRED: US Treasury rates, Fed target and the broad trade-weighted USD index.
TFTC: public CC-BY 4.0 US spot BTC ETF flows (SoSoValue/Farside).
DXY (ICE 6-currency index) optional separate public daily Yahoo market quote.
NEVER mislabel Fed broad dollar index as ICE DXY or missing ETF as zero.
"""
import csv
import datetime as dt
import io
import json
import math
import pathlib
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-macro/data")
FRED="https://fred.stlouisfed.org/graph/fredgraph.csv"
TFTC="https://www.tftc.io/bitcoin-etf-flows"
FRED_SERIES={"treasury_2y_pct":"DGS2","treasury_10y_pct":"DGS10",
 "fed_funds_effective_pct":"DFF","fed_target_lower_pct":"DFEDTARL",
 "fed_target_upper_pct":"DFEDTARU","usd_broad_trade_weighted":"DTWEXBGS",
 "fed_balance_sheet_millions":"WALCL"}
MAX_LAG_DAYS={"DGS2":7,"DGS10":7,"DFF":7,"DFEDTARL":7,
 "DFEDTARU":7,"DTWEXBGS":18,"WALCL":18}

def fetch(url,max_bytes=2_000_000):
    req=urllib.request.Request(url,headers={"User-Agent":"BTC-market-data-public-macro-v1/1.0",
         "Accept":"application/json,text/csv,text/plain"})
    for n in range(3):
        try:
            with urllib.request.urlopen(req,timeout=28) as r:
                body=r.read(max_bytes+1)
                if len(body)>max_bytes:raise ValueError("oversized public response")
                return body
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            if isinstance(exc,urllib.error.HTTPError) and exc.code not in (429,500,502,503,504):raise
            if n==2:raise
            time.sleep(n+1)

def finite(x):
    if isinstance(x,bool):return None
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def dateparse(s):
    return dt.date.fromisoformat(str(s)[:10])

def fred_csv(body,series):
    rows={}
    reader=csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    if not reader.fieldnames or series not in reader.fieldnames:
        raise ValueError("wrong FRED CSV header for "+series)
    datecol="observation_date" if "observation_date" in reader.fieldnames else "DATE"
    for row in reader:
        try:
            date=dateparse(row[datecol])
            value=finite(row[series])
            if value is None:continue  # holidays: missing, not zero
            if not 0<=value<1_000_000:raise ValueError("invalid official FRED data")
            rows[date.isoformat()]=value
        except (TypeError,KeyError,ValueError):
            continue
    if len(rows)<15:raise ValueError("insufficient numerical observations "+series)
    return rows

def summarized_fred(rows,series,now):
    latest=max(rows)
    lag=(now.date()-dateparse(latest)).days
    if lag<0:raise ValueError("future FRED observation")
    ordered=sorted(rows)
    current=rows[latest]
    before=rows[ordered[-2]] if len(ordered)>1 else None
    earlier=rows[ordered[-6]] if len(ordered)>=6 else None
    return {"series_id":series,"source_url":"https://fred.stlouisfed.org/series/"+series,
      "date":latest,"lag_days":lag,"status":"usable" if lag<=MAX_LAG_DAYS[series] else "delayed",
      "value":round(current,5) if lag<=MAX_LAG_DAYS[series] else None,
      "latest_reported_even_if_stale":round(current,5),
      "change_prior_obs":round(current-before,5) if before is not None else None,
      "change_5_obs":round(current-earlier,5) if earlier is not None else None,
      "observations":len(rows)}

def get_fred(now):
    records={};series={};errors=[]
    start=(now.date()-dt.timedelta(days=730)).isoformat()
    for name,key in FRED_SERIES.items():
        try:
            url=FRED+"?"+urllib.parse.urlencode({"id":key,"cosd":start})
            rows=fred_csv(fetch(url),key)
            rows={k:v for k,v in rows.items() if dateparse(k)<=now.date()}
            series[name]=summarized_fred(rows,key,now)
            records[key]=rows
        except Exception as exc:
            errors.append(name+": "+str(exc)[:145])
            series[name]={"series_id":key,"date":None,"status":"unavailable","value":None}
    two,ten=records.get("DGS2",{}),records.get("DGS10",{})
    common=sorted(set(two)&set(ten))
    curve=None
    if common:
        date=common[-1];age=(now.date()-dateparse(date)).days
        curve={"date":date,"lag_days":age,
            "spread_pct_points":round(ten[date]-two[date],5) if age<=7 else None,
            "status":"usable" if age<=7 else "delayed",
            "same_day_2y_pct":two[date] if age<=7 else None,
            "same_day_10y_pct":ten[date] if age<=7 else None}
    # Never sum levels with different observation dates.
    return {"as_of_utc":now.isoformat(),"metrics":series,
        "yield_curve_10y_minus_2y":curve,
        "fed_target_source":"FRED DFEDTARL/DFEDTARU; NOT a prediction of next FOMC decision",
        "usd_broad_not_dxy":True,
        "usd_broad_description":"Federal Reserve nominal broad TRADE-WEIGHTED USD, not ICE six-currency DXY",
        "errors":errors},records

def dxy_optional(now):
    # Yahoo chart is unofficial and sometimes explicitly HTTP 429/500 for ICE.
    # On failure expose null, never relabel FRED broad-dollar index as DXY.
    path="https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?"+urllib.parse.urlencode(
         {"range":"1mo","interval":"1d"})
    try:
        raw=json.loads(fetch(path,max_bytes=600_000))
        item=(raw.get("chart",{}).get("result") or [None])[0]
        if not item:raise ValueError("no public ICE DXY market bars")
        stamps=item["timestamp"]
        closes=item["indicators"]["quote"][0]["close"]
        rows=[]
        for s,v in zip(stamps,closes):
            x=finite(v)
            if x is None or x<=0:continue
            d=dt.datetime.fromtimestamp(int(s),UTC).date()
            if d>now.date():continue
            rows.append((d,x))
        if not rows:raise ValueError("no usable USD index close")
        d,val=rows[-1];age=(now.date()-d).days
        return {"source":"Yahoo Finance, DX-Y.NYB (ICE US Dollar Index delayed daily)",
          "date":d.isoformat(),"lag_days":age,"value":round(val,4) if age<=7 else None,
          "status":"usable" if age<=7 else "delayed","instrument":"ICE DXY six-currency index",
          "not_fred_broad_usd":True}
    except Exception as exc:
        return {"source":"Yahoo Finance DX-Y.NYB","status":"unavailable","value":None,
                "not_fred_broad_usd":True,"error":str(exc)[:160]}

def validate_etf_latest(j,now):
    if not isinstance(j,dict):raise ValueError("ETF latest JSON must be object")
    if "spot" not in str(j.get("name","")).lower() or not str(j.get("license","")).endswith("/by/4.0/"):
        raise ValueError("incorrect ETF market scope or missing open data license")
    item=j.get("latestSession")
    if not isinstance(item,dict):raise ValueError("no published ETF session")
    day=dateparse(item["date"])
    if day>now.date() or day.weekday()>4:raise ValueError("impossible/future ETF session date")
    total=finite(item.get("netFlowUsd"))
    if total is None:raise ValueError("ETF flow missing is not zero")
    funds=item.get("perEtfUsd")
    details_verified=False
    if isinstance(funds,dict) and len(funds)>=8 and all(finite(v) is not None for v in funds.values()):
        difference=abs(sum(float(v) for v in funds.values())-total)
        if difference>5_000_000:raise ValueError("ETF per-fund sum differs from official aggregate by >5m")
        details_verified=True
    trailing=j.get("recentSessions") or []
    if len(trailing)<5:raise ValueError("missing ETF trailing-five sessions")
    recent=[]
    for r in trailing[:5]:
        day2=dateparse(r["date"])
        n=finite(r.get("netFlowUsd"))
        if n is None or day2>now.date():raise ValueError("invalid ETF trailing session")
        recent.append({"date":day2.isoformat(),"net_flow_usd":n})
    if recent[0]["date"]!=day.isoformat() or len({r["date"] for r in recent})!=5:
        raise ValueError("ETF 5-session data not consecutive published sessions")
    # Three business days since last published session triggers stale flag;
    # weekends/US holidays can delay a complete row, never fill it with zeros.
    after=sum((day+dt.timedelta(days=x)).weekday()<5 for x in range(1,(now.date()-day).days+1))
    usable=after<=3
    return {"status":"usable" if usable else "delayed",
      "source":"The Commoner BTC ETF Tracker by TFTC",
      "source_url":"https://www.tftc.io/bitcoin-etf-flows",
      "data_url":TFTC+"/latest.json","license":"CC BY 4.0",
      "attribution":j.get("attribution"),
      "methodology_url":j.get("methodologyUrl"),
      "date":day.isoformat(),"business_days_since_session":after,
      "latest_net_flow_usd":round(total,2) if usable else None,
      "five_sessions_net_flow_usd":round(sum(r["net_flow_usd"] for r in recent),2) if usable else None,
      "five_sessions_positive":sum(r["net_flow_usd"]>0 for r in recent),
      "five_sessions_negative":sum(r["net_flow_usd"]<0 for r in recent),
      "last_five_sessions":recent,
      "per_fund_verified":details_verified,
      "per_fund_flow_usd":funds if details_verified and usable else None,
      "market":"US-listed spot BTC ETFs only, no futures or international funds",
      "note":"creation/redemption flows after US trading session; revisions possible; not intraday trading volume"}

def etf_history(data,now):
    # This optional source can have a different schema; validate rows
    # before computing a 21-session total. Failure leaves 21-session null.
    rows=None
    if isinstance(data,list):rows=data
    elif isinstance(data,dict):
        for key in ("sessions","daily","data","rows","history","dailyFlows"):
            if isinstance(data.get(key),list):
                rows=data[key];break
    if rows is None:raise ValueError("unsupported full ETF history schema")
    dates={}
    for row in rows:
        if not isinstance(row,dict):continue
        date=row.get("date") or row.get("day")
        val=finite(row.get("netFlowUsd"))
        if val is None or date is None:continue
        try:d=dateparse(date)
        except ValueError:continue
        if d<=now.date() and d.weekday()<5:dates[d.isoformat()]=val
    clean=sorted(dates.items())
    if len(clean)<21:raise ValueError("less than 21 dated fund flow sessions")
    sub=clean[-21:]
    return {"observations":len(clean),"start_date":clean[0][0],
       "end_date":clean[-1][0],"last_21_reported_sessions_net_usd":round(sum(v for _,v in sub),2),
       "window":"21 actually published exchange sessions, NOT calendar 21 days or 30d annualized"}

def main():
    now=dt.datetime.now(UTC)
    macro,history=get_fred(now)
    macro["ice_dxy"]=dxy_optional(now)
    etf={"status":"unavailable","latest_net_flow_usd":None}
    try:
        etf=validate_etf_latest(json.loads(fetch(TFTC+"/latest.json")),now)
        try:
            hist=etf_history(json.loads(fetch(TFTC+"/data.json",max_bytes=12_000_000)),now)
            if hist["end_date"]!=etf["date"]:raise ValueError("full ETF record date mismatches latest")
            etf["historical"]=hist
        except Exception as exc:
            etf["historical"]={"status":"unavailable","error":str(exc)[:155]}
    except Exception as exc:
        etf["error"]=str(exc)[:190]
    out={"schema_version":1,"generated_utc":now.isoformat(),
       "status":"ok" if etf.get("status")=="usable" and
           sum(v.get("status")=="usable" for v in macro["metrics"].values())>=4 else "partial",
       "macro":macro,"etf":etf,
       "quality":{"macro_fred_usable_count":sum(v.get("status")=="usable" for v in macro["metrics"].values()),
          "exact_dxy_status":macro["ice_dxy"]["status"],
          "etf_status":etf.get("status"),
          "macro_and_etf_separately_gated":True},
       "rules":["FRED broad USD is NOT ICE DXY","ETF latest != intraday flows",
                "Fed target bounds are observed policy rates NOT future Fed decisions",
                "Missing rate/ETF observation is not zero; weekends and reporting revisions matter"]}
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/"latest.json").write_text(json.dumps(out,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    (ROOT/"fred_history.json").write_text(json.dumps({"generated_utc":now.isoformat(),
        "series":history},separators=(",",":"),allow_nan=False)+"\n")
    print(json.dumps({"generated":out["generated_utc"],"status":out["status"],
        "fred":{k:(v.get("status"),v.get("date")) for k,v in macro["metrics"].items()},
        "dxy":macro["ice_dxy"]["status"],"etf":etf.get("status"),
        "etf_day":etf.get("date"),"errors":macro["errors"]}))
if __name__=="__main__":main()
