"""BTC derivatives historical feed: exact source/contract/units and coverage."""
import datetime as dt
import json
import math
import pathlib
import urllib.request
from collections import defaultdict

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-derivatives/data")
SHARPE="https://www.sharpe.ai/api"
EXCHANGES=["Binance","Bybit","OKX","Gate","Hyperliquid"]
FUNDING={
    "Binance":("binance","BTCUSDT"),
    "Bybit":("bybit","BTCUSDT"),
    "OKX":("okx","BTC-USDT-SWAP")
}
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"BTC-market-research/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=50) as r:
        return json.load(r)
def number(v):
    x=float(v)
    if not math.isfinite(x):raise ValueError("nonfinite number")
    return x
def dateparse(v):
    return dt.datetime.fromisoformat(str(v).replace("Z","+00:00"))
def status(source,ts,now,max_hours):
    try:age=(now-dateparse(ts)).total_seconds()/3600
    except Exception:return {"source":source,"status":"unknown","age_h":None}
    return {"source":source,"status":"fresh" if 0<=age<=max_hours else "stale","age_h":round(age,2)}

def fetch_oi(now):
    url=SHARPE+"/futures/data?chart=oi-stacked&coin=BTC&timeframe=1M"
    obj=get(url)
    rows=obj.get("data")
    if not isinstance(rows,list) or not rows:raise ValueError("no BTC OI history")
    history=defaultdict(dict)
    for item in rows:
        venue=item.get("exchange")
        if venue not in EXCHANGES:continue
        try:
            timestamp=dateparse(item["timestamp"])
            usd=number(item["open_interest_value"])
            if usd<=0:continue
        except (KeyError,ValueError,TypeError):continue
        hour=timestamp.strftime("%Y-%m-%dT%H:00:00Z")
        history[hour][venue]=round(usd,2)
    last=max(history)
    latest=history[last]
    complete=set(EXCHANGES).issubset(latest)
    daily={}
    for hour,items in sorted(history.items()):
        if set(EXCHANGES).issubset(items):
            daily[hour[:10]]={"hour":hour, "venues":{name:items[name] for name in EXCHANGES},
                "five_venue_usd":round(sum(items[name] for name in EXCHANGES),2)}
    days=sorted(daily)
    changes={}
    for duration in (1,7,30):
        if not days:
            changes[str(duration)+"d"]=None
            continue
        target=(dt.date.fromisoformat(days[-1])-dt.timedelta(days=duration)).isoformat()
        a=daily.get(days[-1]);b=daily.get(target)
        changes[str(duration)+"d"]=(round((a["five_venue_usd"]/b["five_venue_usd"]-1)*100,3)
             if b and b["five_venue_usd"]>0 else None)
    meta=obj.get("meta") or {}
    asof=meta.get("as_of",last)
    return {"source":"Sharpe Terminal /api/futures/data oi-stacked","unit":"USD notional (vendor normalized)",
        "venues":EXCHANGES,"latest_hour":last,"latest_venue_usd":latest,
        "latest_five_venue_usd":round(sum(latest[name] for name in EXCHANGES),2) if complete else None,
        "daily_history":daily,"available_daily_complete":len(daily),"changes_pct":changes,
        "source_meta":status("Sharpe OI",asof,now,3),
        "provider_warnings":meta.get("warnings",[])}

def fetch_funding(now):
    out={}
    for venue,(slug,symbol) in FUNDING.items():
        url=SHARPE+"/funding/rates?type=history&coin=BTC&exchange="+slug+"&days=30&limit=400"
        raw=get(url)
        if not isinstance(raw,list):raise ValueError("unexpected funding schema for "+venue)
        series={}
        for record in raw:
            if record.get("symbol")!=symbol:continue
            try:
                when=dateparse(record["settled_at"])
                hours=number(record["interval_hours"])
                if not 0<hours<=24:continue
                rate=number(record["rate"])
            except (ValueError,KeyError,TypeError):continue
            series[when.isoformat()]={"raw_rate":rate,"hours":hours,"rate_8h":rate*8/hours}
        records=sorted(series.items())
        dates=[dateparse(t) for t,_ in records]
        gap=max([(b-a).total_seconds()/3600 for a,b in zip(dates,dates[1:])],default=None)
        latest_date=records[-1][0] if records else None
        out[venue]={"symbol":symbol,"source":"Sharpe settled funding history","count":len(records),
            "first":records[0][0] if records else None,"last":latest_date,
            "max_gap_hours":round(gap,2) if gap is not None else None,
            "settlements":series,
            "latest_raw_rate":records[-1][1]["raw_rate"] if records else None,
            "latest_rate_8h":records[-1][1]["rate_8h"] if records else None,
            "mean_rate_8h_30d":round(sum(v["rate_8h"] for _,v in records)/len(records),9) if len(records)>=60 and gap is not None and gap<=16 else None,
            "freshness":status("Sharpe "+venue+" funding",latest_date,now,13)}
    return out

def fetch_liquidations(now):
    out={}
    for window in (24,168):
        obj=get("https://edgeornot.com/api/liquidations?hours="+str(window)+"&coin=btc")
        total=obj.get("total") or {}
        by=obj.get("by_exchange") or {}
        long=number(total["long"]);short=number(total["short"])
        venues={}
        for ex in ("binance","bybit"):
            if ex in by:
                row=by[ex]
                venues[ex]={"long_usd":round(number(row["long"]),2),
                            "short_usd":round(number(row["short"]),2),"events":row.get("n")}
        if not all(ex in venues for ex in ("binance","bybit")):raise ValueError("missing liquidation venue")
        timestamp=obj.get("updated")
        updated=dt.datetime.fromtimestamp(timestamp/1000,UTC).isoformat() if isinstance(timestamp,(float,int)) else None
        out[str(window)+"h"]={"source":"Edge or Not; Binance+Bybit reported forced liquidations",
          "units":"USD; observed venue records; not all global exchange liquidations",
          "updated":updated,"long_usd":round(long,2),"short_usd":round(short,2),
          "venues":venues,"data_freshness":status("Edge liquidations",updated,now,3)}
    return out

def fetch_cme_cot(now):
    url=("https://publicreporting.cftc.gov/resource/gpe5-46if.json?"
      "$where=cftc_contract_market_code%3D%27133741%27%20and%20"
      "report_date_as_yyyy_mm_dd%20%3E%3D%20%272022-01-01%27&"
      "$limit=350&$order=report_date_as_yyyy_mm_dd%20DESC")
    obj=get(url)
    if not isinstance(obj,list) or len(obj)<180:raise ValueError("CFTC history unexpectedly short")
    series={}
    for row in obj:
        if row.get("cftc_contract_market_code")!="133741":continue
        date=row["report_date_as_yyyy_mm_dd"][:10]
        oi=int(row["open_interest_all"])
        if oi<=0:continue
        series[date]={
            "open_interest_contracts":oi,
            "open_interest_btc_equivalent":oi*5,
            "dealer_long":int(row["dealer_positions_long_all"]),
            "dealer_short":int(row["dealer_positions_short_all"]),
            "asset_manager_long":int(row["asset_mgr_positions_long"]),
            "asset_manager_short":int(row["asset_mgr_positions_short"]),
            "leveraged_long":int(row["lev_money_positions_long"]),
            "leveraged_short":int(row["lev_money_positions_short"])}
    dates=sorted(series)
    latest=dates[-1]
    return {"source":"CFTC TFF futures-only BTC CME contract 133741 (5 BTC per contract)",
        "frequency":"weekly Tuesday observation, published later",
        "unit":"CME standard BTC futures CONTRACTS, multiplied by 5 for equivalent BTC",
        "latest_date":latest,"latest":series[latest],
        "weeks":len(series),"history":series,
        "freshness":{"lag_calendar_days":(now.date()-dt.date.fromisoformat(latest)).days,
                     "normal_report_lag":"Friday report of Tuesday position"},
        "futures_only":True,"micro_btc_contracts_not_included":True}

def fetch_basis(now):
    base=SHARPE+"/futures/data?chart="
    snapshot=get(base+"term-structure&coin=BTC&timeframe=1W")
    curve=get(base+"annualized-basis&coin=BTC&timeframe=1W")
    wanted=("Binance","Bybit","OKX","Deribit")
    snap={}
    for row in snapshot.get("data",[]):
        ex=row.get("exchange")
        if ex not in wanted:continue
        try:
            expiry=dateparse(row["expiry_date"])
            t=dateparse(row["timestamp"])
            days=number(row["days_to_expiry"])
            annual=number(row["annualized_basis_pct"])
            spot=number(row["spot_price"]);futures=number(row["futures_price"])
            if days<7 or spot<=0 or futures<=0:continue
        except (ValueError,TypeError,KeyError):continue
        if ex not in snap or days<snap[ex]["days_to_expiry"]:
            snap[ex]={"timestamp":t.isoformat(),"expiry":expiry.date().isoformat(),
                  "contract":row.get("contract_symbol"),"days_to_expiry":round(days,3),
                  "spot_usd":spot,"futures_usd":futures,
                  "annualized_basis_pct_vendor":annual}
    history=defaultdict(dict)
    for row in curve.get("data",[]):
        if row.get("exchange") not in wanted:continue
        try:
            day=dateparse(row["timestamp"]).strftime("%Y-%m-%d")
            ap=number(row["annualized_basis_pct"])
            contract=row.get("contract_symbol","")
            if not contract:continue
            # Calendar contract roll changes the basis; history is contract-labelled.
            history[day][row["exchange"]+"|"+contract]=round(ap,5)
        except (KeyError,ValueError,TypeError):continue
    return {"source":"Sharpe term-structure / annualized-basis history",
      "markets":"dated futures (NOT perpetual funding)",
      "cme_basis":{"status":"missing","reason":"Verified CME matched-settlement futures-vs-spot annualized basis not yet available"},
      "dated_basis_latest_by_venue":snap,"daily_by_venue_and_contract":dict(history),
      "source_meta":status("Sharpe basis",(snapshot.get("meta") or {}).get("as_of"),now,3)}
