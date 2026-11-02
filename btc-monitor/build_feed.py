"""Validated compact bridge for hourly BTC trend-risk automation; stdlib only."""
import datetime as dt
import json
import math
import os
from pathlib import Path

SOURCES={
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
                                       "scope":"fixed selected five spot venues; does not include Coinbase"},
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

TRANSFORM={"spot_cvd":compact_spot,"derivatives":compact_deriv,"options":compact_options,
           "live_depth":compact_live_depth,"hft_depth":compact_hft,"bybit_depth":compact_bybit}

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
  if status=="fresh" and j.get("status") not in (None,"ok"):status="partial"
  # A freshly rebuilt file is NOT proof that its underlying hour is new:
  # CVD trades are published ~2 hours late by design; reject stalled data.
  sampled_at=(timeparse(j.get("last_complete_hour")) if key=="spot_cvd"
              else timeparse(val(j,"current","time")) if key=="live_depth"
              else None)
  sample_age=dt_age(now,sampled_at)
  if status=="fresh" and sample_age is not None:
   if (key=="spot_cvd" and sample_age>5.0) or (key=="live_depth" and sample_age>3.0):
    status="stale_observation"
  feeds[key]={"status":status,"source":url,"generated_at":stamp.isoformat() if stamp else None,
              "measurement_at":sampled_at.isoformat() if sampled_at else None,
              "measurement_age_h":sample_age,
              "age_h":age,"max_age_h":max_age,"family":family,
              "source_status":j.get("status"),
              "source_errors":len(j.get("errors") or j.get("errors_recent_run") or [])}
  try:metrics[key]=compact_onchain(j,now) if key=="onchain" else TRANSFORM[key](j)
  except (ValueError,KeyError,TypeError) as exc:
   feeds[key]["status"]="invalid_schema"
   issues.append(key+":invalid_schema:"+str(exc)[:100]);continue
  if feeds[key]["status"]!="fresh":issues.append(key+":"+feeds[key]["status"])
 coverage_gaps=[]
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
 usable["current_orderbook"]=feeds.get("live_depth",{}).get("status")=="fresh"
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


def make_brief(report):
 """Compact monitor-facing payload; never upgrade stale inputs to fresh."""
 metrics=report["metrics"]; feeds=report["feeds"]
 good=lambda k:feeds.get(k,{}).get("status")=="fresh"
 summary={"schema":1,"as_of_utc":report["as_of_utc"],
          "sources":{k:{"status":v["status"],"age_h":v.get("age_h"),
                         "original":v.get("source"),"measurement_age_h":v.get("measurement_age_h"),"source_errors":v.get("source_errors",0)} for k,v in feeds.items()},
          "family_readiness":report["audit"]["family_readiness"],
          "issues":report["audit"]["issues"],"coverage_gaps":report["audit"].get("coverage_gaps",[]),
          "rules":["Only fresh source + complete original window/band can support current risk",
                   "Orderbook resting orders are NOT executed purchases; not a world-wide book",
                   "Compare historical orderbook same venue/market/band/UTC clock only",
                   "Bybit 00:00 UTC vs HFT 12:00 UTC cannot be merged",
                   "CVD longer windows are null until 100% complete",
                   "Options RR25 is call-minus-put; CFTC futures shorts may be hedges",
                   "If important independent factors are unavailable reduce confidence; never infer no risk"]}
 if good("spot_cvd"):
  j=metrics["spot_cvd"]
  summary["spot_cvd"]={"last_complete_hour":j.get("last_complete_hour"),
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
 return summary

def main():
 now=timeparse(os.environ.get("BTC_MONITOR_TEST_NOW")) or dt.datetime.now(UTC)
 source={}
 for key,(path,_,_) in SOURCES.items():
  try:source[key]=json.loads(Path(path).read_text(encoding="utf8"))
  except (OSError,ValueError) as exc:
   print("SOURCE_ERROR",key,str(exc),flush=True)
 report=build(source,now)
 out=Path("btc-monitor/data/latest.json");out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf8")
 brief_path=Path("btc-monitor/data/brief.json")
 brief_path.write_text(json.dumps(make_brief(report),indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf8")
 print(json.dumps({"as_of":report["as_of_utc"],"feed_status":{k:v["status"] for k,v in report["feeds"].items()},
                   "audit":report["audit"],"file_bytes":out.stat().st_size},ensure_ascii=False),flush=True)
 if len(report["metrics"])<5:raise SystemExit("Risk bridge insufficient parsed feeds: expected at least five")

if __name__=="__main__":main()
