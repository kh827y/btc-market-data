"""BTC derivatives historical feed: exact source/contract/units and coverage."""
import datetime as dt
import json
import math
import io
import zipfile
import pathlib
import urllib.request
from collections import defaultdict

UTC=dt.timezone.utc
ROOT=pathlib.Path("btc-derivatives/data")
SHARPE="https://www.sharpe.ai/api"
EXCHANGES=["Binance","Bybit","OKX","Gate.io","Hyperliquid"]
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
    return {"source":source,"status":"fresh" if -0.1<=age<=max_hours else "stale","age_h":round(age,2)}

# Free, keyless derivatives provider. The former Sharpe endpoints started
# returning HTTP 401 in November 2026, so they cannot be primary inputs.
COINBOSS="https://www.coinboss.com/api"

def coinboss(path):
    result=get(COINBOSS+path)
    if not isinstance(result,dict) or result.get("success") is not True:
        raise ValueError("CoinBoss unsuccessful response: "+str(result.get("code") if isinstance(result,dict) else type(result)))
    return result

def msdate(value):
    t=dt.datetime.fromtimestamp(number(value)/1000,UTC)
    return t.isoformat()

def fetch_oi(now):
    """The same five named exchange totals, not a global OI estimate.

    CoinBoss reports all BTC contract classes per venue; Bybit and Gate may
    report double-sided OI. Never splice this history to old Sharpe history.
    """
    live=coinboss("/sd/oi?coin=BTC")
    chart=coinboss("/oi/chart?coin=BTC&hours=720")
    rows=live.get("by_exchange") or []
    venue_ids={"Binance":"binance","Bybit":"bybit","OKX":"okx",
               "Gate.io":"gate","Hyperliquid":"hyperliquid"}
    latest={}
    conventions={}
    for venue,slug in venue_ids.items():
        matches=[x for x in rows if isinstance(x,dict) and x.get("exchange")==slug]
        if len(matches)!=1:
            raise ValueError("missing or ambiguous OI venue "+venue)
        row=matches[0]
        age=(now-dt.datetime.fromtimestamp(number(row["updated_at"])/1000,UTC)).total_seconds()
        if row.get("is_stale") is True or not -180<=age<=1800:
            raise ValueError("stale OI observation "+venue)
        latest[venue]=round(number(row["oi_usd"]),2)
        conventions[venue]=row.get("oi_side")
        if latest[venue]<=0:raise ValueError("nonpositive OI "+venue)
    history={}
    for row in chart.get("data") or []:
        if not isinstance(row,dict):continue
        try:
            at=dt.datetime.fromtimestamp(number(row["ts"])/1000,UTC)
            if not -dt.timedelta(minutes=10)<=now-at<=dt.timedelta(hours=730):
                continue
            values=row["byExchange"]
            hourly={venue:round(number(values[slug]),2)
                    for venue,slug in venue_ids.items()}
            if not all(v>0 for v in hourly.values()):continue
            hour=at.strftime("%Y-%m-%dT%H:00:00Z")
            history[hour]=hourly
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
    if not history:raise ValueError("no complete CoinBoss five-venue OI hours")
    last=max(history)
    daily={}
    for hour,venues in sorted(history.items()):
        day=hour[:10]
        daily[day]={"hour":hour,"venues":venues,
                    "five_venue_usd":round(sum(venues.values()),2)}
    days=sorted(daily)
    changes={}
    for span in (1,7,30):
        start=(dt.date.fromisoformat(days[-1])-dt.timedelta(days=span)).isoformat()
        previous=daily.get(start)
        current=daily[days[-1]]
        changes[str(span)+"d"]=(round((current["five_venue_usd"]/
            previous["five_venue_usd"]-1)*100,3)
            if previous and previous["five_venue_usd"]>0 else None)
    return {"source":"CoinBoss public exchange-collected BTC OI, per-venue USD notional",
        "source_url":COINBOSS+"/sd/oi?coin=BTC",
        "unit":"USD notional (vendor normalized)","venues":EXCHANGES,
        "latest_hour":last,"latest_venue_usd":latest,
        "latest_five_venue_usd":round(sum(latest.values()),2),
        "daily_history":daily,"available_daily_complete":len(daily),
        "changes_pct":changes,"oi_side_conventions":conventions,
        "source_meta":status("CoinBoss OI",last,now,3),
        "provider_warnings":["New CoinBoss series; do not join to historical Sharpe OI",
            "Bybit/Gate can report double-sided OI; USD values are vendor-reported, not necessarily single-sided",
            "All BTC contracts per named venue; not solely BTCUSDT perp; compare only like-for-like source and contract scopes"]}

def fetch_funding(now):
    """Only settled funding, never indicative/predicted funding."""
    obj=coinboss("/sd/funding?coin=BTC")
    if obj.get("unit")!="fraction":raise ValueError("funding rate unit not fraction")
    accum=coinboss("/funding/accumulated?base=BTC&days=7")
    series=accum.get("series") or []
    result={}
    wanted={"Binance":("binance","BTCUSDT"),
            "Bybit":("bybit","BTCUSDT"),
            "OKX":("okx","BTC-USDT-SWAP")}
    for venue,(slug,symbol) in wanted.items():
        candidates=[x for x in obj.get("by_exchange",[])
                    if x.get("exchange")==slug and x.get("primary") is True]
        if len(candidates)!=1:continue
        row=candidates[0]
        normalized_symbol=str(row.get("symbol","")).replace("-","")
        if normalized_symbol!=symbol.replace("-",""):continue
        settled=row.get("settled") or {}
        if not isinstance(settled,dict) or not settled.get("last_time"):continue
        try:
            interval=number(settled.get("interval_h") or row.get("interval_h"))
            last=msdate(settled["last_time"])
            last_rate=number(settled["last_rate"])
            if not (0<interval<=24 and abs(last_rate)<=0.05):continue
            age=(now-dateparse(last)).total_seconds()/3600
            if not -0.2<=age<=20:continue
            matching=[a for a in series if a.get("exchange")==slug and
                       str(a.get("symbol","")).replace("-","")==normalized_symbol]
            if len(matching)!=1:continue
            history=matching[0]
            points=history.get("points") or []
            timestamps=sorted({number(x[0]) for x in points
                               if isinstance(x,list) and len(x)==2})
            if len(timestamps)<2:continue
            if abs(number(settled["last_time"])-timestamps[-1])>interval*3600000:
                continue
            max_gap=max((b-a)/3600000 for a,b in zip(timestamps,timestamps[1:]))
            if max_gap>48:continue
            result[venue]={"symbol":symbol,"source":"CoinBoss verified settled funding",
                "count":len(timestamps),"first":msdate(timestamps[0]),"last":last,
                "max_gap_hours":round(max_gap,2),
                "latest_raw_rate":last_rate,
                "latest_rate_8h":last_rate*8/interval,
                "settlements_7d_complete":bool(history.get("complete")),
                "funding_interval_hours":interval,
                "freshness":status("CoinBoss settled "+venue,last,now,20)}
        except (ValueError,TypeError,KeyError,OverflowError):continue
    if not result:raise ValueError("no verified settled BTC funding on named venues")
    return result

def fetch_liquidations(now):
    """Only observed Binance+Bybit forced liquidations, excluding other venues."""
    obj=coinboss("/sd/liquidations?coin=BTC")
    sources={str(x.get("exchange")):x for x in obj.get("sources",[])
             if isinstance(x,dict)}
    rows=((obj.get("by_exchange") or {}).get("24h") or [])
    by={str(r.get("exchange")):r for r in rows if isinstance(r,dict)}
    venues={}
    for name in ("binance","bybit"):
        if name not in by or name not in sources:
            raise ValueError("missing Binance/Bybit liquidation coverage")
        state=str(sources[name].get("status","")).upper()
        if state not in ("FRESH","HEALTHY","OK"):
            raise ValueError("stale liquidation source: "+name)
        row=by[name]
        long_usd=number(row["long_usd"])
        short_usd=number(row["short_usd"])
        if long_usd<0 or short_usd<0:raise ValueError("negative liquidation")
        venues[name]={"long_usd":round(long_usd,2),
                      "short_usd":round(short_usd,2),
                      "events":row.get("count")}
    timestamp=msdate(obj["now"])
    if not -0.2<=(now-dateparse(timestamp)).total_seconds()/3600<=2:
        raise ValueError("liquidation source clock stale")
    return {"24h":{"source":"CoinBoss public recorded BTC Binance+Bybit liquidation orders",
        "updated":timestamp,"long_usd":round(sum(v["long_usd"] for v in venues.values()),2),
        "short_usd":round(sum(v["short_usd"] for v in venues.values()),2),
        "venues":venues,"data_freshness":status("CoinBoss liquidation feeds",timestamp,now,2),
        "units":"Observed forced orders in USD notional, two named venues only; exchange stream may undercount"}}

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
    by_expiry=defaultdict(dict)
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
        one={"timestamp":t.isoformat(),"expiry":expiry.date().isoformat(),
                  "contract":row.get("contract_symbol"),"days_to_expiry":round(days,3),
                  "spot_usd":spot,"futures_usd":futures,
                  "annualized_basis_pct_vendor":annual}
        by_expiry[expiry.date().isoformat()][ex]=one
        if ex not in snap or days<snap[ex]["days_to_expiry"]:
            snap[ex]=one
    common=[date for date,v in by_expiry.items() if set(wanted).issubset(v)]
    shared_date=min(common) if common else None
    matched=by_expiry[shared_date] if shared_date else None
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
      "dated_basis_latest_by_venue":snap,
      "matched_four_venue_expiry":shared_date,"matched_four_venue_basis":matched,
      "daily_by_venue_and_contract":dict(history),
      "source_meta":status("Sharpe basis",(snapshot.get("meta") or {}).get("as_of"),now,3)}

def fetch_cme_basis(now):
    """Dated CME Bitcoin futures versus timestamp-matched spot/index; Boros."""
    root="https://historical-data.boros.finance/futures-premium/"
    series={}
    for expiry in ("20260626","20260925","20261225","20270326"):
        url=root+"cme-BTC-"+expiry+".ndjson.zip"
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 BTC-research/1.0"})
        with urllib.request.urlopen(req,timeout=45) as resp:
            blob=resp.read(2500000)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            files=archive.namelist()
            if len(files)!=1:raise ValueError("unexpected CME zipped contents")
            lines=archive.read(files[0]).splitlines()
        rows={}
        for raw in lines:
            data=json.loads(raw)
            try:
                when=dateparse(data["datetime"])
                duration=number(data["daysToExpiry"])
                spot=number(data["spotPrice"])
                future=number(data["futuresPrice"])
                ap=number(data["premiumApr"])
                symbol=data["contractSymbol"]
                if ".CME" not in symbol or duration<=7 or spot<=0 or future<=0:
                    continue
                if data.get("isSpotProxy") is True:
                    continue
                calculated=((future/spot)-1)*365/duration
                if abs(calculated-ap)>0.03:
                    continue
                day=when.strftime("%Y-%m-%d")
                # Keep last observed rate of the day per CME expiry.
                if day not in rows or when.isoformat()>rows[day]["timestamp"]:
                    rows[day]={"timestamp":when.isoformat(),"contract":symbol,
                        "expiry":expiry,"days_to_expiry":round(duration,4),
                        "spot_usd":spot,"futures_usd":future,
                        "annualized_basis_pct":round(ap*100,5)}
            except (KeyError,TypeError,ValueError):
                continue
        if not rows:raise ValueError("no valid CME matched-price observations for "+expiry)
        series[expiry]=rows
    latest={}
    for expiry,rows in series.items():
        day=max(rows)
        last=rows[day]
        latest[expiry]={"date":day,**last}
    recent={exp:record for exp,record in latest.items()
        if 0<=(now.date()-dt.date.fromisoformat(record["date"])).days<=7
          and dt.datetime.strptime(exp,"%Y%m%d").date()>now.date()}
    front=min(recent) if recent else None
    return {"source":"Boros Historical Data / futures-premium CME directly identified contracts",
        "source_url":"https://historical-data.boros.finance/index.html",
        "method":"(futuresPrice/spotPrice-1)*365/daysToExpiry; percent; same-row joined spot within ±1h",
        "series_by_expiry":series,"points":sum(map(len,series.values())),
        "latest_by_expiry":latest,
        "front_recent_contract":latest[front] if front else None,
        "status":"recent_observed" if front else "stale_or_unavailable",
        "warning":"CME holidays/weekends produce multi-day gaps; near-expiry <7d excluded; not a continuous roll-adjusted series"}

def main():
    now=dt.datetime.now(UTC)
    # Retired Sharpe 401 endpoints; retain only independently validated live feeds.
    checks=(("open_interest",fetch_oi),("funding",fetch_funding),
            ("liquidations",fetch_liquidations),("cme_cot",fetch_cme_cot),
            ("cme_basis",fetch_cme_basis))
    results={};errors=[]
    for key,fn in checks:
        try:
            results[key]=fn(now)
            print("SUCCESS",key)
        except Exception as exc:
            errors.append({"dataset":key,"error":str(exc)[:250]})
            print("ERROR",key,str(exc)[:250])
    last_report=ROOT/"latest.json"
    cme_basis_available=bool((results.get("cme_basis") or {}).get("front_recent_contract"))
    report={
        "generated_utc":now.isoformat(),
        "source_classes":{
            "open_interest":"multi-venue USD notional; 5-venue fixed set",
            "funding":"actually settled contract rates; converted to a common 8h settlement basis",
            "liquidations":"reported USD forced liquidations from Binance and Bybit only",
            "liquidations_30d_vendor":"30 days of observed Binance+Bybit liquidation vendor quantity, not mixed with Edge",
            "cme_cot":"weekly BTC CME standard futures only, positions in 5 BTC contracts",
            "dated_futures_basis":"expiry-aware non-CME futures/spot basis, not funding",
            "cme_basis":"historical verified CME dated futures premium against matched spot from Boros, not proxy"},
        "results":results,"errors":errors,
        "coverage":{"obtained":len(results),"expected":len(checks),
                    "core_feeds_available":all(k in results for k in ("open_interest","funding","liquidations")),
                    "complete":len(results)==len(checks) and cme_basis_available,
                    "cme_basis_available":cme_basis_available},
        "limitations":[
            "CME basis from independently labelled Boros CME price history, NOT CFTC. When source stale or a contract is close to expiration mark unavailable.",
            "OI, settled funding and liquidations use CoinBoss exchange-collected public data after Sharpe 401; verify source ages and venues.",
            "Liquidations from only two exchanges are NOT world totals. Binance sampling may undercount forced orders.",
            "Monthly vendor-only liquidation quantity and four-exchange matched dated basis are unavailable after Sharpe 401; do not synthesize them.",
            "CoinBoss reported OI may include contract kinds and double-sided venue conventions; never silently compare historical Sharpe figures.",
            "Funding settlement rates are periodic fractions, not APR; compare aligned 8h normalizations.",
            "Futures contract rolls break a continuous dated basis curve unless expiry is retained.",
            "CFTC COT weekly reporting lags and is a different scope from perpetual OI."
        ]
    }
    ROOT.mkdir(parents=True,exist_ok=True)
    last_report.write_text(json.dumps(report,ensure_ascii=False,separators=(",",":"))+"\n")
    print("COVERAGE",report["coverage"],"ERRORS",len(errors))
    # Exit nonzero for missing critical observations. A GitHub Actions green
    # check must never mean a snapshot was complete when APIs returned 401.
    if not report["coverage"]["core_feeds_available"]:
        raise SystemExit("Critical derivatives not refreshed: OI/funding/liquidations missing")
if __name__=="__main__":
    main()

# Source-observation quality gate is evaluated downstream in btc-monitor/metric_quality.py.
