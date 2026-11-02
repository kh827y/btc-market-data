"""Validated compact bridge for hourly BTC trend-risk automation; stdlib only."""
import datetime as dt
import json
import math
import os
from pathlib import Path

SOURCES={
 "macro_etf":("btc-macro/data/latest.json",26.0,"macro_liquidity"),
 "price_technical":("btc-price/data/latest.json",26.0,"price_trend"),
 "spot_cvd":("btc-spot-cvd/data/latest.json",2.5,"spot_execution"),
 "derivatives":("btc-derivatives/data/latest.json",3.0,"positioning"),
 "options":("btc-options/data/latest.json",3.0,"options"),
 "onchain":("btc-onchain/data/monitor_latest.json",36.0,"holder_behavior"),
 "live_depth":("btc-liquidity/data/latest.json",2.5,"orderbook"),
 "hft_depth":("btc-liquidity/data/hft_latest.json",36.0,"orderbook"),
 "bybit_depth":("btc-liquidity/data/bybit_independent_latest.json",36.0,"orderbook"),
}
UTC=dt.timezone.utc

def val(o,*path):
 for p in path:
  if not isinstance(o,dict):return None
  o=o.get(p)
 return o

def timeparse(value):
 if not value:return None
 try:
  value=str(value)
  if len(value)==10:value+="T00:00:00+00:00"
  t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
  return t if t.tzinfo else t.replace(tzinfo=UTC)
 except (TypeError,ValueError,OverflowError):return None

def num(x):
 if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x):return x
 return None

def dt_age(now, t):
 return round((now-t).total_seconds()/3600,2) if t else None

def guard_bands(book):
 out={}
 for band,v in (book or {}).items():
  if not isinstance(v,dict):continue
  ok=v.get("bid_coverage_complete") is True and v.get("ask_coverage_complete") is True
  out[band]={"complete":ok,"bid_usd":num(v.get("bid_usd")) if ok else None,
             "ask_usd":num(v.get("ask_usd")) if ok else None,
             "bid_share":(num(v.get("bid_share")) if num(v.get("bid_share")) is not None else num(v.get("imbalance_bid_share"))) if ok else None}
 return out

def compact_spot(j):
 windows={}
 for k in ("1h","24h","168h","720h"):
  row=val(j,"windows",k) or {}
  ok=row.get("complete") is True
  subset=row.get("complete_venue_subset") or {}
  scoped_ok=(subset.get("available") is True and len(subset.get("venues") or [])>=3
             and all((row.get("by_venue") or {}).get(v,{}).get("complete") is True
                     for v in subset.get("venues",[])))
  alt=row.get("fixed_five_ex_coinbase") or {}
  alt_ok=(alt.get("complete") is True and
          alt.get("venues")==["binance","okx","bybit","kraken","bitget"] and
          all((row.get("by_venue") or {}).get(n,{}).get("complete") is True for n in alt.get("venues",[])) and
          num(alt.get("net")) is not None)
  windows[k]={"complete":ok,"net_usd_approx":num(row.get("net")) if ok else None,
              "fixed_five_ex_coinbase":{"complete":alt_ok,"venues":alt.get("venues",[]) if alt_ok else [],
                                       "net_usd_approx":num(alt.get("net")) if alt_ok else None,
                                       "scope":"fixed selected five spot venues; does not include Coinbase",
                                     "kraken_official_rest_hours":alt.get("kraken_official_rest_hours"),
                                     "kraken_hour_basis_mixed":alt.get("kraken_hour_basis_mixed") is True,
                                     "kraken_hour_basis_note":alt.get("kraken_hour_basis_note")},
              "complete_venue_subset":{"available":scoped_ok,
                  "venues":subset.get("venues",[]) if scoped_ok else [],
                  "venue_count":len(subset.get("venues",[])) if scoped_ok else 0,
                  "net_usd_approx":num(subset.get("net")) if scoped_ok else None,
                  "not_all_venues":True},
              "venues":{v:{"complete":x.get("complete") is True,
                           "hours":x.get("hours"),"required":x.get("required"),
                           "net_usd_approx":num(x.get("net")) if x.get("complete") is True else None}
                        for v,x in (row.get("by_venue") or {}).items()}}
 return {"last_complete_hour":j.get("last_complete_hour"),"windows":windows,
         "coinbase_window_integrity":j.get("coinbase_window_integrity"),
         "coinbase_recent_repair":j.get("coinbase_recent_repair"),
         "time_basis_note":j.get("time_basis_note"),
         "scope":"executed spot-taker flow on observed venues only; NOT global BTC volume"}

def compact_deriv(j):
 r=j.get("results",{});oi=r.get("open_interest",{})
 cot=r.get("cme_cot",{});basis=r.get("dated_futures_basis",{})
 cme=r.get("cme_basis",{});liq=r.get("liquidations",{})
 return {"source_coverage":j.get("coverage"),"oi_five_venue_usd":num(oi.get("latest_five_venue_usd")),
         "oi_latest_hour":oi.get("latest_hour"),"oi_1d_7d_30d_pct":oi.get("changes_pct"),
         "funding_settled":{k:{"last":v.get("last"),"rate":v.get("latest_raw_rate"),
                                "max_gap_h":v.get("max_gap_hours")}
                             for k,v in r.get("funding",{}).items()},
         "forced_liquidations_24h":{k:val(liq,"24h",k) for k in
                                    ("updated","long_usd","short_usd","data_freshness")},
         "cftc_cme_weekly": {"as_of":cot.get("latest_date"),"positions":cot.get("latest")},
         "dated_futures_matched_expiry":basis.get("matched_four_venue_expiry"),
         "dated_futures_basis":basis.get("matched_four_venue_basis"),
         "cme_front_basis":cme.get("front_recent_contract") if cme.get("status") in ("ok","recent_observed") else None,
         "warnings":["CFTC contracts are 5 BTC; leveraged fund shorts can hedge spot",
                     "CME and dated futures basis are not perp funding; expiry matters"]}

def compact_options(j):
 r=j.get("results",{});dv=r.get("deribit_dvol_history",{})
 a=r.get("deribit_live_surface",{})
 dr=r.get("derivasys_daily_research",{})
 return {"source_coverage":j.get("coverage"),"deribit_as_of":a.get("as_of_utc"),
         "deribit_term":{k:val(a,"term_structure",k) for k in ("1W","2W","1M","3M","6M")},
         "dvol":{"last_date":dv.get("last"),"percent":dv.get("last_dvol_pct"),
                 "percentile":dv.get("percentile_all"),"closed_days":dv.get("history_closed_days")},
         "derivasys_report_date":dr.get("report_date"),
         "derivasys_1m":val(dr,"standard_tenors","1M"),
         "rr25_convention":"call IV minus put IV (negative means more expensive downside puts), in volatility POINTS"}

def compact_onchain(j,now):
 out={}
 for group,fields in {
  "market_onchain":("mvrv","mvrv_zscore","nupl","sth_sopr","lth_sopr","lth_realized_profit","lth_realized_loss","sth_realized_profit","sth_realized_loss","sth_realized_price","lth_realized_price","realized_price","exchange_in_btc","exchange_out_btc","exchange_reserves_btc"),
  "lth_sth_bitview":("lth_supply_150d","sth_supply_150d","lth_change_7d_150d","lth_change_30d_150d","lth_realized_price_150d","sth_realized_price_150d","realized_price_bitview","lth_nupl_150d","sth_nupl_150d"),
  "whale_deposits":("whale_exchange_deposit_count","whale_exchange_deposit_volume_btc","whale_only_top10_deposit_ratio","swiss_whale_deposit_count_ge50"),
  "historical_whale_alerts":("observed_alert_count","observed_btc_volume","count_ge_100_btc","count_ge_1000_btc")
 }.items():
  values={}
  for key in fields:
   row=val(j,"components",group,"latest",key) or {}
   t=timeparse(row.get("date"));lag=(now.date()-t.date()).days if t else None
   component_age=num(val(j,"components",group,"feed_age_hours"))
   ok=(lag is not None and 0<=lag<=3 and num(row.get("value")) is not None
       and row.get("status") not in ("missing","error","delayed")
       and (component_age is None or 0<=component_age<=30))
   values[key]={"date":row.get("date"),"lag_days":lag,"status":"usable" if ok else "missing_or_delayed",
                "value":num(row.get("value")) if ok else None}
  out[group]={"metrics":values,"scope":val(j,"components",group,"scope"),
              "source":val(j,"components",group,"source")}
 # Different measurement methodologies are NEVER silently substituted.
 # The 150-day Bitview UTXO cohorts are distinct from 155-day
 # entity-weighted LTH/STH metrics; network realized price has its own
 # independent provider and may vary slightly even on the same day.
 alternatives={}
 for label,field,kind in (
   ("network_realized_price","realized_price_bitview","bitcoin_utxo_network"),
   ("sth_cost_basis_150d","sth_realized_price_150d","utxo_age_less_than_150d"),
   ("lth_cost_basis_150d","lth_realized_price_150d","utxo_age_at_least_150d"),
 ):
  obs=out["lth_sth_bitview"]["metrics"][field]
  alternatives[label]={"value":obs["value"],"date":obs["date"],
       "lag_days":obs["lag_days"],"status":obs["status"],
       "source":"Bitview","source_url":"https://bitview.space/api/",
       "methodology":kind,
       "not_interchangeable_with_bgeometrics_155d_cohorts":label!="network_realized_price"}
 return {"groups":out,"cost_basis_independent":alternatives,
         "cost_basis_all_three_usable":all(x["status"]=="usable" for x in alternatives.values()),
         "known_stale":j.get("stale",[]),"missing":j.get("missing",[]),
         "whale_alert_subset_not_all_transfers":True,
         "historical_exact_whale_entity_flows":j.get("exact_multiyear_whale_deposit_history_available") is True}

def compact_live_depth(j):
 out={}
 for venue,r in (val(j,"current","venues") or {}).items():
  out[venue]={"market":r.get("market"),"symbol":r.get("symbol"),
              "captured_at":r.get("captured_at"),"spread_bps":r.get("spread_bps"),
              "reach_pct":r.get("reach_pct"),"bands":guard_bands(r.get("bands"))}
 return {"venues":out,"spot_usable_venues":j.get("spot_usable_venues"),
         "perp_usable_venues":j.get("perpetual_usable_venues"),
         "source_errors":j.get("errors",[])[:5],
         "resting_orders_not_executed_trades":True}

def compact_hft(j):
 venues={}
 for venue,entry in j.get("comparison",{}).items():
  look={}
  for label,value in (entry.get("previous_days") or {}).items():
   look[label]=value if value and value.get("bands") else None
  venues[venue]={"latest_day":entry.get("latest_day"),"lookback":look,
                 "verified_days":val(j,"coverage",venue,"verified_days"),
                 "recent_coverage":{window:val(j,"recent_window_coverage",window,venue)
                                    for window in ("7d","30d","90d","365d")
                                    if val(j,"recent_window_coverage",window,venue)}}
 return {"data_day":j.get("target_anchor_date"),"status":j.get("status"),
         "markets":venues,"time_of_day":"11-13 UTC verified real daily snapshot",
         "not_intraday_average":True,"unverifiable_hour_files_total":j.get("unverifiable_hour_files_total")}

def compact_bybit(j):
 venues={}
 for venue,entry in j.get("comparisons",{}).items():
  venues[venue]={"latest_day":entry.get("latest"),
                 "lookback":{k:x if x and x.get("bands") else None for k,x in entry.get("comparisons",{}).items()},
                 "coverage":val(j,"coverage",venue)}
 return {"data_day":j.get("target_day"),"status":j.get("status"),
         "markets":venues,"time_of_day":"00:00 UTC genuine Bybit daily snapshot",
         "full_source_zip_crc_verified":j.get("full_source_crc_verified") is True,
         "not_intraday_average":True}

def compact_price(j):
 """Never upgrade unfinished or numerically invalid prices to verified technicals."""
 daily=j.get("daily") or {}
 weekly=j.get("weekly") or {}
 ma=daily.get("ma") or {}
 checks=j.get("cross_checks") or {}
 coverage=j.get("coverage") or {}
 if j.get("status")!="ok" or j.get("instrument",{}).get("symbol")!="BTCUSDT":
  raise ValueError("unverified symbol/status for BTC technicals")
 if coverage.get("daily_complete",0)<250 or coverage.get("weekly_complete",0)<210:
  raise ValueError("insufficient completed daily/weekly history")
 if coverage.get("daily_missing")!=0 or coverage.get("weekly_missing")!=0:
  raise ValueError("gaps in technical candle intervals")
 if checks.get("same_venue_daily_weekly_weeks",0)<4:
  raise ValueError("no 1d/1w integrity cross-check")
 price=num(daily.get("close_usdt"))
 weekly_close=num(weekly.get("last_close_usdt"))
 weekly_sma=num(weekly.get("ma200"))
 rsi=num(daily.get("rsi14_wilder"))
 prices=[num(ma.get("ma"+str(n))) for n in (20,50,200)]
 if (price is None or price<=0 or weekly_close is None or weekly_close<=0
     or weekly_sma is None or weekly_sma<=0 or rsi is None or not 0<=rsi<=100
     or any(x is None or x<=0 for x in prices)):
  raise ValueError("invalid numeric BTC trend indicators")
 if not timeparse(j.get("last_closed_day_utc")) or not timeparse(j.get("last_closed_week_monday_utc")):
  raise ValueError("undated closed BTC candle")
 cross=checks.get("coinbase_daily") or {}
 if cross.get("status")=="verified":
  delta=num(cross.get("absolute_difference_pct"))
  if delta is None or not 0<=delta<=3:
   raise ValueError("unverified/mismatched Coinbase spot price")
 quote=j.get("spot_quote") or {}
 current=num(quote.get("price_usdt"))
 current_at=timeparse(quote.get("observed_utc"))
 return {"source":"Binance BTCUSDT spot (USDT); not worldwide BTC/USD index",
   "last_closed_day_utc":j["last_closed_day_utc"],
   "last_closed_week_monday_utc":j["last_closed_week_monday_utc"],
   "latest_closed_day_price_usdt":price,
   "daily_ma":{"ma20":prices[0],"ma50":prices[1],"ma200":prices[2]},
   "daily_rsi14_wilder":rsi,"rsi14_previous":num(daily.get("rsi14_previous")),
   "daily_change_pct":daily.get("change_pct"),
   "volume_vs_20d_median":num(daily.get("volume_vs_prev20d_median")),
   "breakout20":daily.get("breakout20"),"swings":daily.get("swings"),
   "weekly_close_usdt":weekly_close,"weekly_ma200":weekly_sma,
   "weekly_ma200_rising":weekly_sma>num(weekly.get("prev_ma200")) if num(weekly.get("prev_ma200")) is not None else None,
   "weekly_above_ma200":weekly_close>weekly_sma,
   "trend":j.get("trend",{}).get("classification"),
   "latest_spot_price_usdt":current if current is not None and current>0 and current_at else None,
   "latest_spot_observed_utc":current_at.isoformat() if current_at else None,
   "independent_coinbase_status":cross.get("status"),
   "independent_coinbase_difference_pct":num(cross.get("absolute_difference_pct")),
   "confidence":"cross_venue_verified" if cross.get("status")=="verified" else "single_venue",
   "completed_daily_bars":coverage["daily_complete"],
   "completed_weekly_bars":coverage["weekly_complete"],
   "closed_candles_only":True,
   "spot_not_futures":True}

def compact_macro_etf(j,now):
 if j.get("schema_version")!=1:raise ValueError("invalid macro/ETF schema")
 data=val(j,"macro","metrics") or {}
 required={"treasury_2y_pct":"DGS2","treasury_10y_pct":"DGS10",
    "fed_funds_effective_pct":"DFF","fed_target_upper_pct":"DFEDTARU",
    "fed_target_lower_pct":"DFEDTARL","usd_broad_trade_weighted":"DTWEXBGS",
    "fed_balance_sheet_millions":"WALCL"}
 results={}
 for key,series in required.items():
  row=data.get(key) or {}
  date=timeparse(row.get("date"))
  lag=(now.date()-date.date()).days if date else None
  v=num(row.get("value"))
  limit=18 if series in ("DTWEXBGS","WALCL") else 7
  ok=(row.get("series_id")==series and row.get("status")=="usable"
       and lag is not None and 0<=lag<=limit and v is not None
       and 0<=v<(100_000_000 if series=="WALCL" else 1_000_000))
  results[key]={"date":date.date().isoformat() if date else None,
     "status":"usable" if ok else "missing_or_delayed","value":v if ok else None,
     "unit":"index Jan 2006=100" if series=="DTWEXBGS" else
            "USD millions" if series=="WALCL" else "annual interest percentage points",
     "series_id":series,"source_url":"https://fred.stlouisfed.org/series/"+series,
     "lag_days":lag}
 curve=val(j,"macro","yield_curve_10y_minus_2y") or {}
 curve_dt=timeparse(curve.get("date"))
 curve_age=(now.date()-curve_dt.date()).days if curve_dt else None
 crv=num(curve.get("spread_pct_points"))
 curve_ok=curve.get("status")=="usable" and curve_age is not None and 0<=curve_age<=7 and crv is not None
 if curve_ok:
  # Each source may have a different LATEST trading day. The curve must
  # contain two yields measured on the SAME exact observation date.
  a=num(curve.get("same_day_2y_pct"))
  b=num(curve.get("same_day_10y_pct"))
  curve_ok=a is not None and b is not None and abs((b-a)-crv)<=0.005
 curve_out={"status":"usable" if curve_ok else "missing_or_delayed",
            "date":curve.get("date") if curve_ok else None,
            "spread_pct_points":crv if curve_ok else None}
 raw=val(j,"macro","ice_dxy") or {}
 date=timeparse(raw.get("date"))
 age=(now.date()-date.date()).days if date else None
 exact=num(raw.get("value"))
 source_stamp=timeparse(raw.get("fetched_utc")) or timeparse(j.get("generated_utc"))
 intraday_age=dt_age(now,source_stamp)
 intraday_ok=(raw.get("observation_kind")!="unfinished_current_session" or
              (intraday_age is not None and -.2<=intraday_age<=2.5))
 dxy_ok=(raw.get("status")=="usable" and
         raw.get("not_fred_broad_usd") is True and
         raw.get("instrument")=="ICE DXY six-currency index" and
         exact is not None and exact>0 and age is not None and 0<=age<=7
         and intraday_ok)
 dxy={"value":exact if dxy_ok else None,"date":raw.get("date") if dxy_ok else None,
      "status":"usable" if dxy_ok else "unavailable_or_delayed",
      "source":raw.get("source"),"exact_ice_index":True,
      "observation_kind":raw.get("observation_kind") if dxy_ok else None,
      "fetched_utc":source_stamp.isoformat() if source_stamp else None,
      "intraday_quote_age_h":intraday_age if raw.get("observation_kind")=="unfinished_current_session" else None,
      "not_finalized_eod":raw.get("observation_kind")=="unfinished_current_session" if dxy_ok else None}
 raw=val(j,"etf") or {}
 date=timeparse(raw.get("date"));age=(now.date()-date.date()).days if date else None
 total=num(raw.get("latest_net_flow_usd"))
 recent=raw.get("last_five_sessions") or []
 values=[num(a.get("net_flow_usd")) for a in recent if isinstance(a,dict)]
 etf_ok=(raw.get("status")=="usable" and raw.get("license")=="CC BY 4.0"
         and raw.get("market","").startswith("US-listed spot BTC ETFs")
         and date is not None and age is not None and 0<=age<=7
         and total is not None and abs(total)<=20_000_000_000
         and len(recent)==5 and len(values)==5 and all(x is not None for x in values)
         and abs(values[0]-total)<=0.01
         and abs(sum(values)-(num(raw.get("five_sessions_net_flow_usd")) or 0))<=0.1)
 history=raw.get("historical") or {}
 last21=num(history.get("last_21_reported_sessions_net_usd"))
 hist_ok=(etf_ok and history.get("end_date")==raw.get("date") and
         isinstance(history.get("observations"),int) and history["observations"]>=21 and last21 is not None)
 etf={"status":"usable" if etf_ok else "missing_or_delayed",
      "latest_session_date":raw.get("date") if etf_ok else None,
      "net_flow_usd":total if etf_ok else None,
      "five_sessions_net_flow_usd":sum(values) if etf_ok else None,
      "five_sessions_positive":raw.get("five_sessions_positive") if etf_ok else None,
      "five_sessions_negative":raw.get("five_sessions_negative") if etf_ok else None,
      "per_fund_verified":raw.get("per_fund_verified") is True if etf_ok else False,
      "per_fund_flow_usd":raw.get("per_fund_flow_usd") if etf_ok and raw.get("per_fund_verified") is True else None,
      "last_21_reported_sessions_net_flow_usd":last21 if hist_ok else None,
      "source":"The Commoner Bitcoin ETF Tracker by TFTC (SoSoValue aggregate; Farside issuer history)",
      "attribution":"TFTC (tftc.io/bitcoin-etf-flows), CC BY 4.0",
      "url":"https://www.tftc.io/bitcoin-etf-flows",
      "US_spot_only":True,"not_intraday":True}
 return {"fred":results,"treasury_curve":curve_out,
    "dxy_exact":dxy,"usd_broad_index_is_NOT_dxy":True,
    "us_spot_bitcoin_etf":etf,
    "quality":{"fed_rates":all(results[k]["status"]=="usable" for k in
       ("fed_funds_effective_pct","fed_target_upper_pct","fed_target_lower_pct")),
       "treasury_yields":all(results[k]["status"]=="usable" for k in ("treasury_2y_pct","treasury_10y_pct"))
             and curve_ok,
       "usd_broad_index":results["usd_broad_trade_weighted"]["status"]=="usable",
       "ice_dxy_exact":dxy_ok,"spot_etf_flow":etf_ok},
    "caveats":["Observed Fed target is not probability of next FOMC move",
               "FRED trade-weighted broad USD is NOT ICE 6-currency DXY",
               "ETF flows settle after US market close and may be revised",
               "Rising Treasury yields, DXY and risk assets are not mechanically causal"]}

TRANSFORM={"spot_cvd":compact_spot,"derivatives":compact_deriv,"options":compact_options,
           "live_depth":compact_live_depth,"hft_depth":compact_hft,"bybit_depth":compact_bybit,
           "price_technical":compact_price,"macro_etf":compact_macro_etf}

def observation_time(key,record):
 # Reference end-times of verified windows, not data file creation times.
 if key=="spot_cvd":
  t=timeparse(record.get("last_complete_hour"))
  return t+dt.timedelta(hours=1) if t else None
 if key=="live_depth":
  return timeparse(val(record,"current","time"))
 if key=="price_technical":
  t=timeparse(record.get("last_closed_day_utc"))
  return t+dt.timedelta(days=1) if t else None
 if key=="hft_depth":
  t=timeparse(record.get("target_anchor_date"))
  return t+dt.timedelta(hours=12) if t else None
 if key=="bybit_depth":
  return timeparse(record.get("target_day"))
 return None

def live_book_usable_counts(metrics):
 counts={"spot":0,"perpetual":0}
 venues=val(metrics,"live_depth","venues") or {}
 for venue,row in venues.items():
  market=row.get("market")
  if market in counts and any(b.get("complete") is True for b in (row.get("bands") or {}).values()):
   counts[market]+=1
 return counts

def build(source,now):
 feeds={};metrics={};issues=[]
 for key,(path,max_age,family) in SOURCES.items():
  j=source.get(key)
  url=f"https://github.com/kh827y/btc-market-data/blob/main/{path}"
  if not isinstance(j,dict):
   feeds[key]={"status":"unavailable","source":url,"family":family}
   issues.append(key+":unavailable");continue
  stamp=timeparse(j.get("generated_utc") or j.get("generated_at"))
  age=dt_age(now,stamp)
  status="invalid_timestamp" if age is None else "future_timestamp" if age<-.2 else "stale" if age>max_age else "fresh"
  # Independently dated FRED and ETF rows stay usable when other
  # components fail; never infer missing data from one bad source.
  if status=="fresh" and j.get("status") not in (None,"ok"):
   if not (key=="macro_etf" and j.get("status")=="partial"):
    status="partial"
  # A freshly rebuilt file is NOT proof that its underlying hour is new:
  # CVD trades are published ~2 hours late by design; reject stalled data.
  sampled_at=observation_time(key,j)
  sample_age=dt_age(now,sampled_at)
  if status=="fresh" and sample_age is not None:
   if (key=="spot_cvd" and sample_age>5.0) or (key=="live_depth" and sample_age>3.0) or (
      key in ("hft_depth","bybit_depth") and sample_age>72.0):
    status="stale_observation"
  # A candle is dated by its OPEN. Validate the actual UTC CLOSE separately.
  # BTC trades every day; a completed day's indicators are usable throughout
  # the following UTC day, even if the hourly GitHub cron was delayed.
  if key=="price_technical" and status=="fresh":
   day=timeparse(j.get("last_closed_day_utc"))
   week=timeparse(j.get("last_closed_week_monday_utc"))
   expected_day=now.date()-dt.timedelta(days=1)
   expected_week=now.date()-dt.timedelta(days=now.weekday()+7)
   if (day is None or day.date()!=expected_day or
       week is None or week.date()!=expected_week or
       sample_age is None or sample_age<-.2 or sample_age>24.2):
    status="stale_observation"
  quote_at=timeparse(val(j,"spot_quote","observed_utc")) if key=="price_technical" else None
  quote_age=dt_age(now,quote_at)
  quote_value=num(val(j,"spot_quote","price_usdt")) if key=="price_technical" else None
  quote_ok=(key=="price_technical" and status=="fresh" and
            quote_value is not None and quote_value>0 and
            quote_age is not None and -.2<=quote_age<=2.5)
  feeds[key]={"status":status,"source":url,"generated_at":stamp.isoformat() if stamp else None,
              "measurement_at":sampled_at.isoformat() if sampled_at else None,
              "measurement_age_h":sample_age,
              "spot_quote_status":("fresh" if quote_ok else "unavailable_or_stale") if key=="price_technical" else None,
              "spot_quote_age_h":quote_age if key=="price_technical" else None,
              "age_h":age,"max_age_h":max_age,"family":family,
              "source_status":j.get("status"),
              "source_errors":len(j.get("errors") or j.get("errors_recent_run") or []),
              "collector_health":("errors_present" if j.get("errors") or j.get("errors_recent_run")
                                  else "partial" if j.get("status")=="partial" else "ok")}
  try:
   metrics[key]=compact_onchain(j,now) if key=="onchain" else compact_macro_etf(j,now) if key=="macro_etf" else TRANSFORM[key](j)
   if key=="price_technical":
    if not quote_ok:
     metrics[key]["latest_spot_price_usdt"]=None
     metrics[key]["latest_spot_observed_utc"]=None
    metrics[key]["spot_quote_status"]="fresh" if quote_ok else "unavailable_or_stale"
  except (ValueError,KeyError,TypeError) as exc:
   feeds[key]["status"]="invalid_schema"
   issues.append(key+":invalid_schema:"+str(exc)[:100]);continue
  if feeds[key]["status"]!="fresh":issues.append(key+":"+feeds[key]["status"])
 coverage_gaps=[]
 if feeds.get("macro_etf",{}).get("status")!="fresh":
  coverage_gaps.append("macro_etf:unavailable_or_stale")
 elif "macro_etf" in metrics:
  if feeds["macro_etf"].get("source_status")=="partial":
   coverage_gaps.append("macro_etf:partial_source")
  for component in ("fed_rates","treasury_yields","usd_broad_index","ice_dxy_exact","spot_etf_flow"):
   if val(metrics,"macro_etf","quality",component) is not True:
    coverage_gaps.append("macro_etf:"+component+"_unavailable")
 if feeds.get("price_technical",{}).get("status")!="fresh":
  coverage_gaps.append("btc_technicals:unavailable_or_stale")
 elif feeds.get("price_technical",{}).get("spot_quote_status")!="fresh":
  coverage_gaps.append("btc_spot_quote:unavailable_or_stale")
 if "spot_cvd" in metrics:
  for window in ("24h","168h","720h"):
   if val(metrics,"spot_cvd","windows",window,"complete") is not True:
    coverage_gaps.append("spot_cvd:"+window+"_five_venue_incomplete")
 if "live_depth" in feeds and feeds["live_depth"].get("source_errors",0):
  coverage_gaps.append("live_depth:failed_venues="+str(feeds["live_depth"]["source_errors"]))
 if "onchain" in metrics:
  delayed=sum(v.get("status")!="usable" for g in metrics["onchain"]["groups"].values() for v in g["metrics"].values())
  if delayed:coverage_gaps.append("onchain:missing_or_delayed_metrics="+str(delayed))
 if "derivatives" in metrics and val(metrics,"derivatives","cme_front_basis") is None:
  coverage_gaps.append("derivatives:cme_front_basis_unavailable")
 usable={family:any(row.get("status")=="fresh" and row.get("family")==family for row in feeds.values())
         for family in sorted({x[2] for x in SOURCES.values()})}
 book_counts=live_book_usable_counts(metrics)
 usable["current_orderbook"]=feeds.get("live_depth",{}).get("status")=="fresh" and sum(book_counts.values())>0
 usable["current_spot_orderbook"]=feeds.get("live_depth",{}).get("status")=="fresh" and book_counts["spot"]>0
 usable["current_perp_orderbook"]=feeds.get("live_depth",{}).get("status")=="fresh" and book_counts["perpetual"]>0
 usable["current_spot_orderbook_venues"]=book_counts["spot"] if usable["current_spot_orderbook"] else 0
 usable["current_perp_orderbook_venues"]=book_counts["perpetual"] if usable["current_perp_orderbook"] else 0
 usable["macro_fed_rates"]=feeds.get("macro_etf",{}).get("status")=="fresh" and val(metrics,"macro_etf","quality","fed_rates") is True
 usable["macro_treasury_yields"]=feeds.get("macro_etf",{}).get("status")=="fresh" and val(metrics,"macro_etf","quality","treasury_yields") is True
 usable["macro_usd_broad_not_dxy"]=feeds.get("macro_etf",{}).get("status")=="fresh" and val(metrics,"macro_etf","quality","usd_broad_index") is True
 usable["macro_exact_ice_dxy"]=feeds.get("macro_etf",{}).get("status")=="fresh" and val(metrics,"macro_etf","quality","ice_dxy_exact") is True
 usable["us_spot_btc_etf_flows"]=feeds.get("macro_etf",{}).get("status")=="fresh" and val(metrics,"macro_etf","quality","spot_etf_flow") is True
 usable["price_technical_verified"]=feeds.get("price_technical",{}).get("status")=="fresh"
 usable["price_live_spot_quote"]=usable["price_technical_verified"] and feeds.get("price_technical",{}).get("spot_quote_status")=="fresh"
 usable["price_technical_cross_venue"]=usable["price_technical_verified"] and val(metrics,"price_technical","confidence")=="cross_venue_verified"
 usable["onchain_independent_cost_basis"]=feeds.get("onchain",{}).get("status")=="fresh" and val(metrics,"onchain","cost_basis_all_three_usable") is True
 usable["spot_cvd_24h_complete"]=feeds.get("spot_cvd",{}).get("status")=="fresh" and val(metrics,"spot_cvd","windows","24h","complete") is True
 usable["spot_cvd_24h_covered_subset"]=feeds.get("spot_cvd",{}).get("status")=="fresh" and val(metrics,"spot_cvd","windows","24h","complete_venue_subset","available") is True
 usable["spot_cvd_24h_fixed_five_ex_coinbase"]=feeds.get("spot_cvd",{}).get("status")=="fresh" and val(metrics,"spot_cvd","windows","24h","fixed_five_ex_coinbase","complete") is True
 for h in ("168h","720h"):
  usable["spot_cvd_"+h+"_fixed_five_ex_coinbase"]=feeds.get("spot_cvd",{}).get("status")=="fresh" and val(metrics,"spot_cvd","windows",h,"fixed_five_ex_coinbase","complete") is True
 return {"schema":1,"as_of_utc":now.isoformat(),
         "feed_contract":"Source-level UTC quality bridge; not a standalone reversal signal",
         "audit":{"sources_total":len(SOURCES),"sources_parsed":len(metrics),
                  "fresh":sum(x.get("status")=="fresh" for x in feeds.values()),
                  "issues":issues,"coverage_gaps":coverage_gaps,"family_readiness":usable,
                  "WARNING":"Bridge generation success DOES NOT imply source freshness or all-market coverage"},
         "feeds":feeds,"metrics":metrics,
         "rules":["Trust only source rows with status=fresh for current conditions",
                  "Also check original source measurement date and complete window/band for each indicator",
                  "A daily historical snapshot is not live orderbook or a daily average",
                  "Historical 00:00 and 12:00 UTC daily depths must not be pooled or compared",
                  "Compare orderbook within one venue/market/price band only",
                  "Spot CVD = executed trades; resting book bids/asks are not actual demand",
                  "Funding, OI, options, onchain have dependent indicators: do not double-count",
                  "Missing or stale groups REDUCE conviction, never imply no risk",
                  "No risk/news alert unless genuinely material change; cite source and key indicators"]}


def read_collector_watchdog(now):
 """Independent collector health; never treat it as a price/trend signal."""
 try:
  j=json.loads(Path("btc-monitor/data/health_latest.json").read_text(encoding="utf8"))
 except (OSError,ValueError):
  return {"status":"unavailable","reason":"watchdog_health_feed_unreadable",
          "workflow_api_reachable":False}
 age=dt_age(now,timeparse(j.get("checked_utc")))
 if age is None or age<-.2 or age>1.5:
  return {"status":"stale","checked_utc":j.get("checked_utc"),
          "age_h":age,"reason":"independent_watchdog_stopped",
          "workflow_api_reachable":False}
 items={}
 for name,v in (j.get("sources") or {}).items():
  items[name]={"status":v.get("status"),"reason":v.get("reason"),
       "recovery":val(v,"recovery","action"),
       "workflow_api_error":v.get("workflow_api_error"),
       "file_age_h":v.get("file_age_h"),"coverage_gaps":v.get("coverage_gaps") or []}
 return {"status":j.get("status") if j.get("workflow_api_reachable") is True else "monitoring_blind",
         "checked_utc":j.get("checked_utc"),"age_h":age,
         "workflow_api_reachable":j.get("workflow_api_reachable") is True,
         "unavailable_or_stale":j.get("unavailable_or_stale") or [],
         "auto_recovery":j.get("auto_recovery") or {},"sources":items,
         "caveat":"This feed is not proof that the scheduled ChatGPT run actually read it"}

def make_brief(report):
 """Compact monitor-facing payload; never upgrade stale inputs to fresh."""
 metrics=report["metrics"]; feeds=report["feeds"]
 good=lambda k:feeds.get(k,{}).get("status")=="fresh"
 summary={"schema":1,"as_of_utc":report["as_of_utc"],
          "sources":{k:{"status":v["status"],"age_h":v.get("age_h"),
                         "original":v.get("source"),"measurement_age_h":v.get("measurement_age_h"),
                         "spot_quote_status":v.get("spot_quote_status"),"spot_quote_age_h":v.get("spot_quote_age_h"),
                         "source_errors":v.get("source_errors",0),"collector_health":v.get("collector_health")} for k,v in feeds.items()},
          "family_readiness":report["audit"]["family_readiness"],
          "issues":report["audit"]["issues"],"coverage_gaps":report["audit"].get("coverage_gaps",[]),
          "rules":["Only fresh source + complete original window/band can support current risk",
                   "Orderbook resting orders are NOT executed purchases; not a world-wide book",
                   "Compare historical orderbook same venue/market/band/UTC clock only",
                   "Bybit 00:00 UTC vs HFT 12:00 UTC cannot be merged",
                   "CVD longer windows are null until 100% complete",
                   "Options RR25 is call-minus-put; CFTC futures shorts may be hedges",
                   "If important independent factors are unavailable reduce confidence; never infer no risk"]}
 if good("macro_etf"):
  macro=metrics["macro_etf"]
  summary["macro"]={"fred":macro["fred"],"treasury_curve":macro["treasury_curve"],
       "dxy_exact":macro["dxy_exact"],"usd_broad_index_is_NOT_dxy":True,
       "quality":macro["quality"]}
  summary["us_spot_bitcoin_etf"]=macro["us_spot_bitcoin_etf"]
 if good("price_technical"):
  summary["btc_technicals"]=metrics["price_technical"]
 if good("spot_cvd"):
  j=metrics["spot_cvd"]
  summary["spot_cvd"]={"last_complete_hour":j.get("last_complete_hour"),
     "coinbase_window_integrity":j.get("coinbase_window_integrity"),
     "coinbase_recent_repair":j.get("coinbase_recent_repair"),
     "time_basis_note":j.get("time_basis_note"),
     "windows":{k:{"complete":v["complete"],"net_usd_approx":v["net_usd_approx"],
                "complete_venue_subset":v.get("complete_venue_subset"),
                "fixed_five_ex_coinbase":v.get("fixed_five_ex_coinbase"),
                "venue_coverage_hours":{name:{"hours":vr.get("hours"),"required":vr.get("required"),
                                              "complete":vr.get("complete")}
                                        for name,vr in v.get("venues",{}).items()}}
                for k,v in j["windows"].items()}}
 if good("derivatives"):
  j=metrics["derivatives"]
  summary["derivatives"]={k:j.get(k) for k in ("oi_latest_hour","oi_five_venue_usd",
       "oi_1d_7d_30d_pct","funding_settled","forced_liquidations_24h","cftc_cme_weekly",
       "dated_futures_matched_expiry","cme_front_basis")}
 if good("options"):
  j=metrics["options"]
  summary["options"]={"deribit_as_of":j.get("deribit_as_of"),
    "one_month":val(j,"deribit_term","1M"),
    "dvol":j.get("dvol"),"derivasys_1m":j.get("derivasys_1m")}
 if good("onchain"):
  j=metrics["onchain"]["groups"]
  summary["onchain"]={group:{name:{"value":v["value"],"date":v["date"],"status":v["status"]}
          for name,v in item["metrics"].items()} for group,item in j.items()}
  summary["onchain_cost_basis_independent"]=metrics["onchain"]["cost_basis_independent"]
 if good("live_depth"):
  j=metrics["live_depth"]
  summary["orderbook_live"]={"spot_venues":j["spot_usable_venues"],
    "perpetual_venues":j["perp_usable_venues"],
    "venues":{venue:{"market":item["market"],"captured_at":item["captured_at"],
                     "bands":{k:v for k,v in item["bands"].items()
                              if k in ("0.01","0.05","0.2") and v["complete"]}}
              for venue,item in j["venues"].items()}}
 hist={}
 for src,key,names in (("hft_depth","hft_12utc",("binance_spot","okx_spot","binance_futures","bybit","bybit_spot")),
                       ("bybit_depth","bybit_00utc",("bybit_independent_spot","bybit_independent_linear"))):
  if not good(src):continue
  hist[key]={}
  for venue in names:
   row=val(metrics,src,"markets",venue) or {}
   output={}
   for lag,record in (row.get("lookback") or {}).items():
    if lag not in ("1d","7d","30d","90d","365d","1095d") or not record:continue
    bands={name:value for name,value in record.get("bands",{}).items()
           if name in ("0.01","0.05")}
    if bands:output[lag]={"baseline_day":record.get("baseline_date") or record.get("baseline_day"),
                          "bands":bands}
   hist[key][venue]={"latest_day":row.get("latest_day"),"comparisons":output,
                     "coverage_30d":row.get("recent_coverage",{}).get("30d") if src=="hft_depth" else
                                    row.get("coverage")}
 if hist:summary["orderbook_history"]=hist
 summary["collector_watchdog"]=report.get("collector_watchdog",{
    "status":"not_checked","workflow_api_reachable":False})
 return summary

def main():
 now=timeparse(os.environ.get("BTC_MONITOR_TEST_NOW")) or dt.datetime.now(UTC)
 source={}
 for key,(path,_,_) in SOURCES.items():
  try:source[key]=json.loads(Path(path).read_text(encoding="utf8"))
  except (OSError,ValueError) as exc:
   print("SOURCE_ERROR",key,str(exc),flush=True)
 report=build(source,now)
 report["collector_watchdog"]=read_collector_watchdog(now)
 out=Path("btc-monitor/data/latest.json");out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf8")
 brief_path=Path("btc-monitor/data/brief.json")
 brief_path.write_text(json.dumps(make_brief(report),indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf8")
 print(json.dumps({"as_of":report["as_of_utc"],"feed_status":{k:v["status"] for k,v in report["feeds"].items()},
                   "audit":report["audit"],"file_bytes":out.stat().st_size},ensure_ascii=False),flush=True)
 if len(report["metrics"])<5:raise SystemExit("Risk bridge insufficient parsed feeds: expected at least five")

if __name__=="__main__":main()
