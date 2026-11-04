"""BTC per-metric verification gates. Pure stdlib; no live network calls.

The first layer (build_feed.py) decides whether a FILE is fresh. This
independent second layer checks whether actual instrument-specific MEASUREMENTS
inside it are usable, with their own timestamps, units, selected exchange set,
complete windows, and apples-to-apples comparison requirements.

Each result is machine readable and fail-closed:
  status: usable|unavailable|unverified|stale|invalid|incomplete|not_comparable
No probability, directional trading signal or artificial market coverage is
inferred from a fresh JSON file or complete collector job.
"""
from __future__ import annotations
import datetime as dt
import math

UTC=dt.timezone.utc
ORIGINAL_SPOT=("binance","coinbase","okx","bybit","kraken")
FIXED_EX_COINBASE=("binance","okx","bybit","kraken","bitget")
EXPECTED_LIVE={
    "binance_spot":"spot","bybit_spot":"spot","coinbase_spot":"spot",
    "okx_spot":"spot","bitget_spot":"spot","gate_spot":"spot",
    "binance_usdm_perp":"perpetual","bybit_usdt_perp":"perpetual",
    "okx_usdt_perp":"perpetual","bitget_usdt_perp":"perpetual",
    "gate_usdt_perp":"perpetual"}
WS_TRANSPORTS={"bybit_spot":"bybit_official_ws_snapshot",
               "bybit_usdt_perp":"bybit_official_ws_snapshot",
               "binance_usdm_perp":"binance_official_ws_api_depth"}
# All native timestamped source snapshots are independently date-checked.
# A newly published wrapper never makes an old exchange REST book current.
NATIVE_BOOK_TIMESTAMPS=("okx_spot","okx_usdt_perp","bitget_spot",
                        "bitget_usdt_perp","gate_spot","gate_usdt_perp")
BOOK_TRANSPORTS={
    "binance_spot":("official_public_rest",),
    "coinbase_spot":("official_public_rest",),
    "okx_spot":("official_public_rest","okx_official_rest_400_fallback"),
    "okx_usdt_perp":("official_public_rest","okx_official_rest_400_fallback"),
    "bitget_spot":("official_public_rest",),
    "bitget_usdt_perp":("official_public_rest",),
    "gate_spot":("official_public_rest","gate_official_rest_1000_fallback"),
    "gate_usdt_perp":("official_public_rest","gate_official_ws_v2_full_snapshot"),
}
SPANS={"1h":1,"24h":24,"168h":168,"720h":720}
REPORTABLE=("usable",)

def at(value):
    if not value:return None
    try:
        t=dt.datetime.fromisoformat(str(value).replace("Z","+00:00")
                                  if len(str(value))!=10 else str(value)+"T00:00:00+00:00")
        if t.tzinfo is None:return None
        return t.astimezone(UTC)
    except (TypeError,ValueError,OverflowError):return None

def expiry_date(value):
    """Recognize native CME YYYYMMDD and regular ISO dates, no inferred epoch."""
    if isinstance(value,str) and len(value)==8 and value.isdigit():
        try:return dt.datetime.strptime(value,"%Y%m%d").replace(tzinfo=UTC)
        except ValueError:return None
    return at(value)

def amount(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):return None
    return float(value) if math.isfinite(value) else None

def finite_positive(value):
    v=amount(value)
    return v is not None and v>0

def interval_age(now,value,max_h,allow_future_h=0.15):
    t=at(value)
    if t is None:return "unverified"
    age=(now-t).total_seconds()/3600
    if age< -allow_future_h:return "invalid"
    if age>max_h:return "stale"
    return "usable"

def date_age(now,value,max_days):
    t=at(value)
    if t is None:return "unverified"
    lag=(now.date()-t.date()).days
    if lag<0:return "invalid"
    if lag>max_days:return "stale"
    return "usable"

def nested(obj,*keys):
    for key in keys:
        if not isinstance(obj,dict):return None
        obj=obj.get(key)
    return obj

def is_close(a,b,absolute=0.05,relative=1e-7):
    a,b=amount(a),amount(b)
    return a is not None and b is not None and abs(a-b)<=max(absolute,relative*max(abs(a),abs(b)))

class Gate:
    def __init__(self,feeds,now):
        self.feeds=feeds
        self.now=now
        self.rows={}
        self.warnings=[]
    def add(self,name,source,status,unit,scope,observed_at=None,reason=None,
            comparison_key=None,required=False):
        if self.feeds.get(source,{}).get("status")!="fresh":
            status="stale" if self.feeds.get(source,{}).get("status") in ("stale","stale_observation") else "unavailable"
            reason="parent_source_not_fresh"
        row={"status":status,"source":source,"unit":unit,"scope":scope,
             "observed_at":observed_at,"comparison_key":comparison_key}
        if reason and status!="usable":row["reason"]=reason
        if required:row["required_for_family"]=True
        self.rows[name]=row
        if status!="usable" and required:self.warnings.append(name+":"+status+":"+str(row.get("reason",""))[:75])
        return status=="usable"
    def result(self):
        counts={s:sum(v["status"]==s for v in self.rows.values())
                for s in ("usable","unavailable","unverified","stale","invalid","incomplete","not_comparable")}
        return {"schema":1,"checked_utc":self.now.isoformat(),
                "status":"complete_audit","metrics_checked":len(self.rows),
                "status_counts":counts,"checks":self.rows,
                "critical_issues":self.warnings[:150],
                "policy":"Only status=usable on a fresh parent feed is eligible for a current trend inference; historical context is individually dated",
                "do_not_sum_independent_factors_from_same_family":True}

def gate_spot(g,raw,metrics):
    windows=raw.get("windows") or {}
    end=at(raw.get("last_complete_hour"))
    end_at=end+dt.timedelta(hours=1) if end else None
    fresh=interval_age(g.now,end_at.isoformat() if end_at else None,5)
    for span,hours in SPANS.items():
        item=windows.get(span) or {}
        by=item.get("by_venue") or {}
        proof=nested(raw,"coinbase_window_integrity",span) or {}
        for group,venues,field in (
            ("original_five",ORIGINAL_SPOT,item),
            ("fixed_ex_coinbase",FIXED_EX_COINBASE,item.get("fixed_five_ex_coinbase") or {})):
            net=amount(field.get("net"))
            complete=field.get("complete") is True
            per=[by.get(n) or {} for n in venues]
            native=(all(row.get("complete") is True and
                       row.get("hours")==hours and row.get("required")==hours and
                       amount(row.get("net")) is not None for row in per))
            match=all(row.get("net") is not None for row in per) and net is not None and (
                is_close(sum(float(row["net"]) for row in per),net,absolute=0.1))
            names=(group!="fixed_ex_coinbase" or field.get("venues")==list(FIXED_EX_COINBASE))
            # Published source proof is separate from the count-only complete marker.
            # Collector publishes 24h/168h/720h archive audits; its 1h
            # window is contained in the 24h proof and has exact 1h per-venue
            # completed trade counts. Do not require a nonexistent 1h audit.
            coin_audit=(nested(raw,"coinbase_window_integrity",
                               "24h" if span=="1h" else span) or {})
            coin_proof=(group!="original_five" or
                        (coin_audit.get("all_hours_id_continuous_verified") is True and
                         coin_audit.get("id_continuous_proof_hours")>=hours and
                         coin_audit.get("coinbase_missing_hours_count")==0))
            status=("usable" if (fresh=="usable" and complete and native and match and names and coin_proof)
                    else fresh if fresh!="usable" else "incomplete" if not complete or not native or not coin_proof
                    else "invalid")
            name=f"spot_cvd.{group}.{span}"
            key=f"BTC spot taker executed|{','.join(venues)}|{span}|USD~USDT|exchange-trade-or-received-UTC-hours"
            good=g.add(name,"spot_cvd",status,"approx USD net taker notional",
                       "executed BTC spot on the fixed named venue set only",
                       end_at.isoformat() if end_at else None,
                       reason="source_window_hour_sum_set_or_coinbase_proof_disagrees",
                       comparison_key=key,required=(group=="original_five"))
            if not good:
                if group=="original_five":
                    m=nested(metrics,"spot_cvd","windows",span)
                    if isinstance(m,dict):
                        m["complete"]=False
                        m["net_usd_approx"]=None
                elif group=="fixed_ex_coinbase":
                    m=nested(metrics,"spot_cvd","windows",span,"fixed_five_ex_coinbase")
                    if isinstance(m,dict):
                        m["complete"]=False
                        m["net_usd_approx"]=None
    # Separate subset: changing venue names => cannot compare net across runs.
    for span in SPANS:
        r=windows.get(span) or {}
        sub=r.get("complete_venue_subset") or {}
        venues=sub.get("venues") or []
        valid=(sub.get("available") is True and isinstance(venues,list) and
               len(venues)==len(set(venues)) and len(venues)>=3 and
               all(n in set(ORIGINAL_SPOT)|{"bitget"} for n in venues) and
               all((r.get("by_venue") or {}).get(n,{}).get("complete") is True and
                   (r.get("by_venue") or {}).get(n,{}).get("hours")==SPANS[span]
                   for n in venues) and
               is_close(sub.get("net"),sum(float((r.get("by_venue") or {})[n]["net"]) for n in venues)) if
               all(amount((r.get("by_venue") or {}).get(n,{}).get("net")) is not None for n in venues)
               else False)
        status="usable" if valid and fresh=="usable" else fresh if fresh!="usable" else "incomplete"
        key="spot_cvd.subset."+span
        good=g.add(key,"spot_cvd",status,"approx USD executed taker net",
                   "changing explicitly named venue subset",end_at.isoformat() if end_at else None,
                   comparison_key=f"spot_executed|{','.join(venues)}|{span}|USD~USDT|same_UTC_window")
        if not good:
            m=nested(metrics,"spot_cvd","windows",span,"complete_venue_subset")
            if isinstance(m,dict):
                m["available"]=False;m["net_usd_approx"]=None

def gate_derivatives(g,raw,metrics):
    r=raw.get("results") or {}
    oi=r.get("open_interest") or {}
    expected={"Binance","Bybit","OKX","Gate.io","Hyperliquid"}
    venues=oi.get("venues") or []
    v=oi.get("latest_venue_usd") or {}
    ok=(set(venues)==expected and len(venues)==5 and set(v)==expected and
        all(finite_positive(v.get(n)) for n in expected) and
        finite_positive(oi.get("latest_five_venue_usd")) and
        is_close(sum(float(v[n]) for n in expected),oi.get("latest_five_venue_usd"),
                 absolute=1000,relative=0.0001) and
        oi.get("unit")=="USD notional (vendor normalized)")
    fresh=interval_age(g.now,oi.get("latest_hour"),5.5)
    status="usable" if ok and fresh=="usable" else fresh if fresh!="usable" else "invalid"
    if not g.add("derivatives.oi_five", "derivatives",status,"USD notional",
                 "Binance,Bybit,OKX,Gate.io,Hyperliquid OI, not worldwide",
                 oi.get("latest_hour"),reason="venue_set_sum_unit_or_observation_invalid",
                 comparison_key="same_five_venue_OI_USD",required=True):
        metrics["derivatives"]["oi_five_venue_usd"]=None
        metrics["derivatives"]["oi_1d_7d_30d_pct"]=None
    funding=r.get("funding") or {}
    verified={}
    for venue,item in funding.items():
        last=item.get("last")
        recent=interval_age(g.now,last,20)
        n=amount(item.get("latest_rate_8h"))
        expected_symbol={"Binance":"BTCUSDT","Bybit":"BTCUSDT",
                         "OKX":"BTC-USDT-SWAP"}.get(venue)
        entry=(expected_symbol is not None and item.get("symbol")==expected_symbol
               and n is not None and
               abs(n)<=0.05 and item.get("count",0)>=2 and
               amount(item.get("max_gap_hours")) is not None and
               item["max_gap_hours"]<=48)
        status="usable" if entry and recent=="usable" else recent if recent!="usable" else "invalid"
        name="derivatives.funding_8h."+venue
        if g.add(name,"derivatives",status,"rate fraction per 8h settled interval",
                 "single venue BTCUSDT perp settled funding, not a forecast",
                 last,comparison_key="settled_funding_8h|"+venue):
            verified[venue]={"rate_8h":n,"last":last,"max_gap_h":item["max_gap_hours"]}
    # Never carry a raw unsettled rate labeled as comparable 8h funding.
    metrics["derivatives"]["funding_settled"]=verified
    liq=nested(r,"liquidations","24h") or {}
    liq_venues=liq.get("venues") or {}
    complete=(set(liq_venues)=={"binance","bybit"} and
              all(all(amount(liq_venues[n].get(x)) is not None and
                          liq_venues[n][x]>=0 for x in ("long_usd","short_usd"))
                  for n in liq_venues) and
              all(amount(liq.get(x)) is not None and liq[x]>=0 for x in ("long_usd","short_usd")) and
              all(is_close(sum(liq_venues[n][x] for n in liq_venues),
                           liq[x],absolute=2) for x in ("long_usd","short_usd")))
    current=interval_age(g.now,liq.get("updated"),5.5)
    status="usable" if complete and current=="usable" else current if current!="usable" else "invalid"
    if not g.add("derivatives.liquidations_24h","derivatives",status,"USD forced liquidations",
                 "reported Binance+Bybit 24h only; not worldwide",
                 liq.get("updated"),comparison_key="liquidation_forced|Binance,Bybit|24h"):
        metrics["derivatives"]["forced_liquidations_24h"]={"updated":None,
            "long_usd":None,"short_usd":None,"data_freshness":"unusable"}
    cot=r.get("cme_cot") or {}
    cot_latest=cot.get("latest") or {}
    date=cot.get("latest_date")
    day=date_age(g.now,date,13)
    ok=(cot.get("futures_only") is True and cot.get("unit","").startswith("CME standard BTC futures") and
        all(amount(cot_latest.get(n)) is not None and cot_latest[n]>=0 for n in
            ("dealer_long","dealer_short","asset_manager_long","asset_manager_short","leveraged_long","leveraged_short")) and
        at(date) is not None and at(date).weekday()==1)
    status="usable" if day=="usable" and ok else day if day!="usable" else "invalid"
    if not g.add("derivatives.cftc_cme_weekly","derivatives",status,
                 "CME standard BTC futures contracts of 5 BTC",
                 "weekly Tuesday CFTC observed positions; published with lag; not directional spot sales",
                 date,comparison_key="CME_COT|standard_BTC_futures|5BTC_contract"):
        metrics["derivatives"]["cftc_cme_weekly"]={"as_of":date,"positions":None}
    basis=nested(r,"dated_futures_basis","matched_four_venue_basis") or {}
    expiry=nested(r,"dated_futures_basis","matched_four_venue_expiry")
    same_expiry=(set(basis)=={"Binance","Bybit","OKX","Deribit"} and
                 all(item.get("expiry")==expiry for item in basis.values()) and
                 date_age(g.now,expiry,9999)!="unverified" and
                 at(expiry) is not None and at(expiry).date()>g.now.date())
    rows_ok=(all(finite_positive(item.get("spot_usd")) and finite_positive(item.get("futures_usd")) and
                 amount(item.get("annualized_basis_pct_vendor")) is not None and
                 interval_age(g.now,item.get("timestamp"),5.5)=="usable"
                 for item in basis.values()) if same_expiry else False)
    status="usable" if same_expiry and rows_ok else "invalid"
    if not g.add("derivatives.dated_basis_matched","derivatives",status,
                 "annualized basis percentage points",
                 "four specific dated BTC future contracts, same exact expiry",
                 max((item.get("timestamp") or "" for item in basis.values()),default=None),
                 comparison_key=f"matched_expiry_BTC_basis|{expiry}"):
        metrics["derivatives"]["dated_futures_matched_expiry"]=None
        metrics["derivatives"]["dated_futures_basis"]=None
    cme=nested(r,"cme_basis","front_recent_contract") or {}
    cme_t=date_age(g.now,cme.get("date"),7)
    cme_ok=(finite_positive(cme.get("spot_usd")) and
            finite_positive(cme.get("futures_usd")) and
            amount(cme.get("annualized_basis_pct")) is not None and
            cme.get("contract","").endswith(".CME") and
            at(cme.get("timestamp")) is not None and
            expiry_date(cme.get("expiry")) is not None and expiry_date(cme["expiry"])>g.now)
    status="usable" if cme_t=="usable" and cme_ok else cme_t if cme_t!="usable" else "invalid"
    if not g.add("derivatives.cme_basis","derivatives",status,"annualized pct",
                 "CME dated futures matched to nearby spot observation; expiry-specific",
                 cme.get("timestamp"),comparison_key="CME|"+str(cme.get("contract"))):
        metrics["derivatives"]["cme_front_basis"]=None

def gate_options(g,raw,metrics):
    r=raw.get("results") or {}
    surface=r.get("deribit_live_surface") or {}
    observed=surface.get("as_of_utc")
    age=interval_age(g.now,observed,5.5)
    for term,row in (surface.get("term_structure") or {}).items():
        # A tenor outside the ACTUALLY LISTED Deribit expiries is a
        # legitimate absent observation, not a corrupt option quote.
        # Do not interpolate/extrapolate 1W from the first listed 9d+ expiry.
        status=("unavailable" if row.get("status")=="unavailable" and
                row.get("reason")=="tenor outside observed maturities"
                else "invalid")
        if row.get("status")=="available" and row.get("quality") in ("standard","wide_expiry_bracket"):
            fields=[amount(row.get(k)) for k in ("atm_iv_pct","call25_iv_pct","put25_iv_pct","rr25_call_minus_put_volpts")]
            left,right=at(row.get("expiry_left")),at(row.get("expiry_right"))
            if (all(x is not None for x in fields) and
                all(0<x<500 for x in fields[:3]) and
                is_close(fields[1]-fields[2],fields[3],absolute=0.02) and
                left is not None and right is not None and
                left<right and right>g.now):
                status="usable" if age=="usable" else age
        if age!="usable":status=age
        good=g.add("options.deribit."+term,"options",status,"IV pct; RR25 volatility points",
                   "Deribit BTC mark-IV, expiry-bracketed approximated 25d call minus put",
                   observed,comparison_key="Deribit|BTC|"+term+"|markIV",
                   required=(term=="1M"))
        if not good:
            metrics["options"]["deribit_term"][term]=None
    dvol=r.get("deribit_dvol_history") or {}
    date=dvol.get("last")
    recent=date_age(g.now,date,4)
    ok=(amount(dvol.get("last_dvol_pct")) is not None and 0<dvol["last_dvol_pct"]<500
        and isinstance(dvol.get("history_closed_days"),int) and dvol["history_closed_days"]>=25)
    status="usable" if recent=="usable" and ok else recent if recent!="usable" else "invalid"
    if not g.add("options.dvol_closed_daily","options",status,"DVOL percentage index",
                 "Deribit BTC DVOL expected 30d magnitude; not direction or ATM",
                 date,comparison_key="Deribit|BTC|DVOL|daily_closed"):
        metrics["options"]["dvol"]["percent"]=None
    dr=r.get("derivasys_daily_research") or {}
    date=dr.get("report_date")
    daily=date_age(g.now,date,5)
    row=nested(dr,"standard_tenors","1M") or {}
    m=row.get("metrics") or {}
    is_ok=(row.get("last_report_day")==date and
           dr.get("sign_convention","").startswith("RR25 25") and
           all(amount(nested(m,n,"current")) is not None for n in ("atmIv","rr25","bf25")) and
           0<m["atmIv"]["current"]<500 and abs(m["rr25"]["current"])<=200)
    status="usable" if daily=="usable" and is_ok else daily if daily!="usable" else "invalid"
    if not g.add("options.derivasys_1m_report","options",status,"ATM IV pct; RR25 volatility points",
                 "dated third-party published BTC options daily 1M research, not live",
                 date,comparison_key="Derivasys|BTC|1M|daily_report"):
        metrics["options"]["derivasys_1m"]=None

def gate_macro(g,raw,metrics):
    quality=metrics.get("macro_etf") or {}
    for name in ("fed_rates","treasury_yields","usd_broad_index","ice_dxy_exact","spot_etf_flow"):
        status="usable" if nested(quality,"quality",name) is True else "unverified"
        source_observed= (nested(raw,"etf","date") if name=="spot_etf_flow"
             else nested(raw,"macro","ice_dxy","date") if name=="ice_dxy_exact"
             else nested(raw,"fred","yield_curve_10y_minus_2y","date") if name=="treasury_yields"
             else None)
        g.add("macro."+name,"macro_etf",status,
              "USD ETF flows" if name=="spot_etf_flow" else "pct/index as individually labeled",
              "specific macro or ETF family, NOT an interchangeable global macro index",
              source_observed,comparison_key="macro|"+name,required=True)
    etf=raw.get("etf") or {}
    sessions=etf.get("last_five_sessions") or []
    if isinstance(sessions,list) and len(sessions)==5:
        dates=[a.get("date") for a in sessions if isinstance(a,dict)]
        ok=(len(dates)==5 and len(set(dates))==5 and
            dates==sorted(dates,reverse=True) and
            dates[0]==etf.get("date") and
            all(at(v) is not None for v in dates))
        if not ok:
            g.rows["macro.spot_etf_flow"]["status"]="invalid"
            g.rows["macro.spot_etf_flow"]["reason"]="five_session_dates_duplicated_or_mismatched"
            g.warnings.append("macro.spot_etf_flow:invalid:session_date_integrity")
            quality["quality"]["spot_etf_flow"]=False
            quality["us_spot_bitcoin_etf"]["status"]="missing_or_delayed"
            quality["us_spot_bitcoin_etf"]["net_flow_usd"]=None
            quality["us_spot_bitcoin_etf"]["five_sessions_net_flow_usd"]=None

def gate_onchain(g,raw,metrics):
    m=metrics.get("onchain") or {}
    groups=m.get("groups") or {}
    reference_only={
        ("market_onchain","sth_realized_price"),
        ("market_onchain","lth_realized_price"),
        ("market_onchain","realized_price"),
        ("whale_deposits","whale_exchange_deposit_volume_btc"),
    }
    for group,row in groups.items():
        for key,value in row.get("metrics",{}).items():
            if ((group,key) in reference_only and
                    value.get("status")=="reference_only_delayed"):
                # Explicit historical context, not an unavailable REQUIRED
                # current market factor. Still retain source date and null.
                value["value"]=None
                continue
            good=(value.get("status")=="usable" and
                  amount(value.get("value")) is not None and
                  value.get("lag_days") is not None and
                  0<=value["lag_days"]<=3 and
                  date_age(g.now,value.get("date"),3)=="usable")
            # The source's explicit upstream unusable status always wins.
            origin=nested(raw,"components",group,"latest",key) or {}
            # Some independent upstreams (Bitview, labelled whale archives)
            # publish dated numeric rows without an explicit status field.
            # Permit those ONLY when their own feed age, date and units pass;
            # an explicit delayed/error/stale status always blocks them.
            upstream_good=origin.get("status") in ("usable","ok","fresh",None)
            if origin.get("status") in ("missing","delayed","error","stale"):
                upstream_good=False
            feed_age=nested(raw,"components",group,"feed_age_hours")
            if feed_age is None or amount(feed_age) is None or feed_age>30 or feed_age<0:
                upstream_good=False
            status="usable" if good and upstream_good else "unverified"
            if date_age(g.now,value.get("date"),3)=="stale":status="stale"
            passed=g.add("onchain."+group+"."+key,"onchain",status,
                         "source-defined BTC/ratio/USD; never substitute independent methodology",
                         "onchain collector-specific metric/UTXO cohort; must be source dated",
                         value.get("date"),comparison_key="onchain|"+group+"|"+key,
                         required=(group=="lth_sth_bitview" and key.endswith("realized_price_150d")))
            if not passed:
                value["status"]="missing_or_delayed";value["value"]=None
    alt=m.get("cost_basis_independent") or {}
    for label,v in alt.items():
        source_key={"network_realized_price":"realized_price_bitview",
                    "sth_cost_basis_150d":"sth_realized_price_150d",
                    "lth_cost_basis_150d":"lth_realized_price_150d"}[label]
        original=groups.get("lth_sth_bitview",{}).get("metrics",{}).get(source_key,{})
        if original.get("status")!="usable":
            v["status"]="missing_or_delayed";v["value"]=None
    m["cost_basis_all_three_usable"]=all(x["status"]=="usable" for x in alt.values())

def gate_live(g,raw,metrics):
    data=nested(raw,"current","venues") or {}
    output=metrics.get("live_depth") or {}
    trimmed=output.get("venues") or {}
    for name,market in EXPECTED_LIVE.items():
        r=data.get(name) or {}
        age=interval_age(g.now,r.get("captured_at"),2.5)
        permitted=( (r.get("transport")==WS_TRANSPORTS[name])
                   if name in WS_TRANSPORTS
                   else (r.get("transport") in BOOK_TRANSPORTS.get(name,())))
        fresh=(age=="usable" and r.get("market")==market and
               r.get("symbol") in ("BTCUSD","BTCUSDT") and permitted)
        if name in WS_TRANSPORTS or name in NATIVE_BOOK_TIMESTAMPS:
            source=at(r.get("source_timestamp"));capture=at(r.get("captured_at"))
            fresh=(fresh and source is not None and capture is not None and
                   -10 <= (capture-source).total_seconds() <= 120)
        bands=r.get("bands") or {}
        anygood=False
        for band in ("0.01","0.05","0.2","1.0"):
            item=bands.get(band) or {}
            ok=(fresh and item.get("bid_coverage_complete") is True and
                item.get("ask_coverage_complete") is True and
                amount(item.get("bid_usd")) is not None and item["bid_usd"]>=0 and
                amount(item.get("ask_usd")) is not None and item["ask_usd"]>=0 and
                amount(item.get("imbalance_bid_share")) is not None and
                0<=item["imbalance_bid_share"]<=1)
            status="usable" if ok else age if age!="usable" else "incomplete"
            if g.add("live_depth."+name+"."+band,"live_depth",status,
                     "visible resting bid/ask approximate USD within "+band+"% of own midpoint",
                     market+" BTC book, not executed CVD or guaranteed liquidity",
                     r.get("source_timestamp") or r.get("captured_at"),
                     comparison_key="live_book|"+name+"|"+market+"|"+band):
                anygood=True
            else:
                if name in trimmed and band in trimmed[name].get("bands",{}):
                    trimmed[name]["bands"][band]={"complete":False,
                         "bid_usd":None,"ask_usd":None,"bid_share":None}
        if not anygood:
            trimmed.pop(name,None)
        g.add("live_depth."+name,"live_depth","usable" if anygood else "incomplete",
              "USD notional","own book with >=1 complete both-sided price band",
              r.get("captured_at"),required=True)
    output["spot_usable_venues"]=sum(row.get("market")=="spot" for row in trimmed.values())
    output["perp_usable_venues"]=sum(row.get("market")=="perpetual" for row in trimmed.values())

def gate_historical(g,raw,metrics,kind):
    if kind=="hft_depth":
        source="hft_depth";entries=raw.get("comparison") or {}
        expected_day=raw.get("target_anchor_date")
        lag_hours=72
        lookback_days={"1d":1,"7d":7,"30d":30,"90d":90,"365d":365}
        lookup="previous_days"
        clock=12
    else:
        source="bybit_depth";entries=raw.get("comparisons") or {}
        expected_day=raw.get("target_day")
        lag_hours=72
        lookback_days={"1d":1,"7d":7,"30d":30,"90d":90,"180d":180,"365d":365,"730d":730,"1095d":1095}
        lookup="comparisons"
        clock=0
    current=date_age(g.now,expected_day,3)
    for market,series in entries.items():
        for period,lag in lookback_days.items():
            item=nested(series,lookup,period)
            if not isinstance(item,dict) or not item.get("bands"):continue
            base=at(item.get("baseline_time"))
            recent=at(item.get("latest_time") or item.get("current_time"))
            base_label=item.get("baseline_day") or item.get("baseline_date")
            valid=(base is not None and recent is not None and
                   recent.date().isoformat()==(series.get("latest_day") or series.get("latest")) and
                   base.date().isoformat()==base_label and
                   abs((recent-base).total_seconds()/86400-lag)<=2/24 and
                   abs(recent.hour+recent.minute/60-clock)<=2 and
                   abs(base.hour+base.minute/60-clock)<=2)
            status="usable" if current=="usable" and valid else current if current!="usable" else "not_comparable"
            for band,measure in item["bands"].items():
                fields=("bid_change_pct","ask_change_pct","bid_share_change_pp")
                calculated=(isinstance(measure,dict) and
                            all(amount(measure.get(q)) is not None for q in fields))
                passed=g.add(f"{source}.{market}.{period}.{band}",source,
                     status if calculated else "invalid",
                     "pct / pp changes in same nominal width",
                     "same venue, instrument, UTC clock, validated snapshot and observed depth",
                     recent.isoformat() if recent else None,
                     comparison_key=f"historical_book|{source}|{market}|{period}|{band}")
                if not passed:
                    if isinstance(measure,dict):
                        # Quarantine invalid comparisons before the trend
                        # briefing can possibly use their percentage changes.
                        measure.clear()
    # Export explicitly dated summary; this is NOT a live intraday book.

def assess(source,feeds,metrics,now):
    g=Gate(feeds,now)
    if isinstance(source.get("spot_cvd"),dict) and isinstance(metrics.get("spot_cvd"),dict):
        gate_spot(g,source["spot_cvd"],metrics)
    if isinstance(source.get("derivatives"),dict) and isinstance(metrics.get("derivatives"),dict):
        gate_derivatives(g,source["derivatives"],metrics)
    if isinstance(source.get("options"),dict) and isinstance(metrics.get("options"),dict):
        gate_options(g,source["options"],metrics)
    if isinstance(source.get("macro_etf"),dict) and isinstance(metrics.get("macro_etf"),dict):
        gate_macro(g,source["macro_etf"],metrics)
    if isinstance(source.get("onchain"),dict) and isinstance(metrics.get("onchain"),dict):
        gate_onchain(g,source["onchain"],metrics)
    if isinstance(source.get("live_depth"),dict) and isinstance(metrics.get("live_depth"),dict):
        gate_live(g,source["live_depth"],metrics)
    for k in ("hft_depth","bybit_depth"):
        if isinstance(source.get(k),dict) and isinstance(metrics.get(k),dict):
            gate_historical(g,source[k],metrics,k)
    # Price has its own verified candle/RSI/Wilder/MA20+50+200 cross checks.
    p=metrics.get("price_technical")
    if isinstance(p,dict):
        # The completed weekly bar is dated by its open Monday. Age-based
        # 8-day gates wrongly reject it midway through the following week.
        expected_day=(now.date()-dt.timedelta(days=1)).isoformat()
        expected_week=(now.date()-dt.timedelta(days=now.weekday()+7)).isoformat()
        g.add("price.closed_daily_weekly","price_technical","usable" if
              p.get("closed_candles_only") is True and
              p.get("last_closed_day_utc")==expected_day and
              p.get("last_closed_week_monday_utc")==expected_week
              else "invalid",
              "BTCUSDT price, RSI Wilder, UTC daily/weekly",
              "Binance SPOT completed candles; not current unclosed week",
              p.get("last_closed_day_utc"),required=True)
        g.add("price.live_spot_quote","price_technical","usable" if
              p.get("spot_quote_status")=="fresh" and
              interval_age(now,p.get("latest_spot_observed_utc"),2.5)=="usable"
              else "stale",
              "BTCUSDT spot USDT per BTC",
              "Binance SPOT ticker, not Coinbase BTCUSD",
              p.get("latest_spot_observed_utc"))
    return g.result()
