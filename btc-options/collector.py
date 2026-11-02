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
    gap_limit=110 if days_target>=90 else 50
    if right["days"]-left["days"]>gap_limit:
        return {"status":"unavailable","reason":"expiry interpolation gap exceeds quality limit"}
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
                   "expiry_gap_days":round(right["days"]-left["days"],2),
                   "quality":"wide_expiry_bracket" if right["days"]-left["days"]>50 else "standard",
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

def fetch_dvol(now):
    start=now-dt.timedelta(days=366)
    data=fetch_deribit("get_volatility_index_data",{
        "currency":"BTC","start_timestamp":int(start.timestamp()*1000),
        "end_timestamp":int(now.timestamp()*1000),"resolution":"1D"})
    candles=data.get("data",[])
    if len(candles)<80:raise ValueError("Deribit DVOL daily history unexpectedly short")
    history={}
    today=now.date()
    for candle in candles:
        try:
            when=dt.datetime.fromtimestamp(int(candle[0])/1000,UTC)
            if when.date()>=today:continue
            o,h,l,c=map(float,candle[1:5])
            if not all(math.isfinite(x) and 0<x<300 for x in (o,h,l,c)):continue
            history[when.date().isoformat()]=round(c,4)
        except (ValueError,IndexError,TypeError,OverflowError):continue
    if len(history)<80:raise ValueError("Deribit DVOL history has <80 valid full days")
    days=sorted(history)
    last=days[-1]
    recent=history[last]
    allv=list(history.values())
    previous_30=[history[d] for d in days if (dt.date.fromisoformat(last)-dt.date.fromisoformat(d)).days<=30]
    return {"source":"Deribit BTC DVOL volatility index (30d expectation); NOT ATM IV",
        "history_closed_days":len(history),"first":days[0],"last":last,
        "last_dvol_pct":recent,"percentile_all":round(sum(v<=recent for v in allv)/len(allv)*100,2),
        "mean_last_30d_pct":round(sum(previous_30)/len(previous_30),4),
        "last_date_lag_days":(today-dt.date.fromisoformat(last)).days,
        "scope":"DVOL index distinct from 1M ATM IV; no current partial-day candle published"}
def fetch_research(now):
    start="2026-04-22";end=now.date().isoformat()
    items=[]
    cursor=None
    for page_count in range(18):
        query={"start":start,"end":end,"limit":31}
        if cursor:query["cursor"]=cursor
        url=RESEARCH+"/observations?"+urllib.parse.urlencode(query)
        obj=get(url)
        records=obj.get("observations",[])
        if not isinstance(records,list):raise ValueError("Derivasys observations schema invalid")
        items.extend(records)
        if not obj.get("hasMore"):break
        next_cursor=obj.get("nextCursor")
        if not next_cursor or next_cursor==cursor:raise ValueError("stalled Derivasys pagination")
        cursor=next_cursor
    else:raise ValueError("Derivasys history exceeded expected pages")
    if len(items)<30:raise ValueError("Derivasys history insufficient")
    byday={}
    for observation in items:
        day=observation.get("reportDate")
        if not day:continue
        byday[day]=observation
    last=max(byday)
    row=byday[last]
    if (row.get("provenance") or {}).get("rrConvention")!="25-delta call IV minus 25-delta put IV":
        raise ValueError("RR25 convention unexpectedly changed")
    series=defaultdict(dict)
    for day,observation in byday.items():
        for tenor in observation.get("tenors",[]):
            key=tenor.get("tenor")
            if tenor.get("availability")!="available" or key not in TENORS:continue
            metrics={}
            for field in ("atmIv","rr25","bf25"):
                value=(tenor.get(field) or {}).get("current")
                if value is None:continue
                try:
                    val=float(value)
                    if not math.isfinite(val):continue
                    metrics[field]=val
                except (TypeError,ValueError):continue
            if len(metrics)==3:series[key][day]=metrics
    summary={}
    for tenor,records in series.items():
        if tenor!="1M" or last not in records:continue
        obs=records[last]
        days=sorted(records)
        metrics={}
        for field in ("atmIv","rr25","bf25"):
            vals=[v[field] for v in records.values()]
            value=obs[field]
            prev7=(dt.date.fromisoformat(last)-dt.timedelta(days=7)).isoformat()
            prev30=(dt.date.fromisoformat(last)-dt.timedelta(days=30)).isoformat()
            metrics[field]={"current":round(value,4),"percentile_available":round(sum(x<=value for x in vals)/len(vals)*100,2),
                           "change_7d_volpts":round(value-records[prev7][field],4) if prev7 in records else None,
                           "change_30d_volpts":round(value-records[prev30][field],4) if prev30 in records else None}
        summary[tenor]={"last_report_day":last,"n_published_observations":len(records),"metrics":metrics}
    # Quote only a limited single-tenor excerpt; do not republish vendor data.
    return {"source":"Derivasys published research; permitted limited excerpts with attribution",
        "source_url":"https://api.derivasys.com/api/v1/data/BTC/latest",
        "history_api":"https://api.derivasys.com/api/v1/data/BTC/observations",
        "research_report":"https://www.derivasys.com/reports/"+last,
        "license":"https://www.derivasys.com/research-artifact-license/v1",
        "report_date":last,"snapshot_at":row.get("timestamps",{}).get("currentSnapshotAt"),
        "published_days":len(byday),
        "sign_convention":"RR25 25Δ call minus 25Δ put; negative=put wing richer",
        "standard_tenors":summary,
        "raw_daily_republication":False}

def main():
    now=dt.datetime.now(UTC)
    ROOT.mkdir(parents=True,exist_ok=True)
    results={}
    errors=[]
    for key,fn in (("deribit_live_surface",fetch_chain),
                   ("deribit_dvol_history",fetch_dvol),
                   ("derivasys_daily_research",fetch_research)):
        try:
            results[key]=fn(now)
            print("OBTAINED",key)
        except Exception as exc:
            errors.append({"dataset":key,"error":str(exc)[:220]})
            print("ERROR",key,str(exc)[:220])
    path=ROOT/"derived_history.json"
    history=json.loads(path.read_text()) if path.exists() else {}
    live=results.get("deribit_live_surface")
    if live:
        timestamp=now.replace(minute=0,second=0,microsecond=0).isoformat()
        entry={}
        for name,v in live["term_structure"].items():
            if v.get("status")=="available":
                entry[name]={"atm_iv_pct":v["atm_iv_pct"],
                             "rr25_volpts":v["rr25_call_minus_put_volpts"],
                             "bf25_volpts":v["bf25_volpts"]}
        if entry:history[timestamp]=entry
    threshold=now-dt.timedelta(days=90)
    for key in list(history):
        try:
            if dt.datetime.fromisoformat(key)<threshold:del history[key]
        except ValueError:del history[key]
    path.write_text(json.dumps(history,separators=(",",":"))+"\n")
    research=results.get("derivasys_daily_research",{})
    latest_report=research.get("report_date")
    latest_age=(now.date()-dt.date.fromisoformat(latest_report)).days if latest_report else None
    report={"generated_utc":now.isoformat(),
            "sources":{
               "Deribit":"public BTC option chain, independent 25-delta approximate forwards and DVOL history",
               "Derivasys":"direct public daily ATM IV/RR25/BF25 2026-04-22+ research; no complete raw republication"},
            "results":results,"errors":errors,
            "coverage":{"collected":len(results),"expected":3,
                        "current_1m_deribit":bool(live and live["term_structure"].get("1M",{}).get("status")=="available"),
                        "derivasys_published_days":research.get("published_days",0),
                        "derivasys_report_lag_days":latest_age,
                        "dvol_closed_days":results.get("deribit_dvol_history",{}).get("history_closed_days",0),
                        "all_sources_retrieved":len(results)==3},
            "limitations":[
              "DVOL is a forward volatility index, not exactly ATM IV.",
              "Deribit surface mark-IV interpolation with forward proxy; do not treat as a broker executable 25-delta quote or Derivasys fitted SVI.",
              "Derivasys research measured daily near 17:31 UTC; same-day intraday option movement is NOT captured in their daily archive.",
              "RR25 convention call minus put; negative implies put IV greater than call IV; fixed tenor must bracket two expiries.",
              "Historical vendor full raw feed deliberately not redistributed due to research artifact license.",
              "Source observations, timestamps and missing tenors are not zero.",
            ]}
    (ROOT/"latest.json").write_text(json.dumps(report,ensure_ascii=False,separators=(",",":"))+"\n")
    print("QUALITY",json.dumps(report["coverage"]), "errors",len(errors))
if __name__=="__main__":
    main()
