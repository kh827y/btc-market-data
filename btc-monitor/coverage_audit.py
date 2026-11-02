"""Evidence-grounded source coverage closeout for hourly BTC trend monitor.

This is a diagnostic inventory, not a market signal and not an artificial
substitution. It exposes the actual *band* coverage for each selected venue
(including levels and both-side reach) and separates delayed original onchain
series from a fresh but methodologically different independent UTXO 150d source.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

UTC=dt.timezone.utc
ROOT=Path("btc-monitor/data")
BOOKS={
 "binance_spot":"spot","bybit_spot":"spot","coinbase_spot":"spot",
 "okx_spot":"spot","bitget_spot":"spot","gate_spot":"spot",
 "binance_usdm_perp":"perpetual","bybit_usdt_perp":"perpetual",
 "okx_usdt_perp":"perpetual","bitget_usdt_perp":"perpetual",
 "gate_usdt_perp":"perpetual",
}
BANDS=("0.01","0.05","0.2","1.0")
COST_BASIS={
 "realized_price":"network_realized_price",
 "sth_realized_price":"sth_cost_basis_150d",
 "lth_realized_price":"lth_cost_basis_150d",
}
BANDS_IN_SCOPE=sorted(BANDS,key=float)

def load(p):
    try:
        with Path(p).open(encoding="utf-8") as f:return json.load(f)
    except (OSError,ValueError,TypeError):return {}

def build(brief,source,original_onchain,hft,bybit,deep):
    quality=(brief.get("metric_quality") or {}).get("checks") or {}
    sources=brief.get("sources") or {}
    booksource=(source.get("current") or {}).get("venues") or {}
    x={"schema":1,
       "assembled_at_utc":dt.datetime.now(UTC).isoformat(),
       "source_brief_as_of_utc":brief.get("as_of_utc"),
       "not_a_market_trend_signal":True,
       "no_unobserved_depth_inferred":True,
       "no_provider_methodologies_silently_substituted":True,
       "no_new_external_requests":True}
    markets={}
    perband={k:{"usable_count":0,"missing_venues":[],"expected_markets":len(BOOKS)} for k in BANDS}
    for name,kind in BOOKS.items():
        raw=booksource.get(name) or {}
        checks={b:quality.get("live_depth."+name+"."+b) or {} for b in BANDS}
        trusted=(quality.get("live_depth."+name) or {}).get("status")=="usable"
        detail={"market":kind,"symbol":raw.get("symbol"),
           "transport":raw.get("transport"),"source_url":raw.get("source_url"),
           "captured_at":raw.get("captured_at"),"source_timestamp":raw.get("source_timestamp"),
           "source_id":raw.get("source_book_id") or raw.get("lastUpdateId"),
           "levels":raw.get("levels"),
           "actual_reach_pct":raw.get("reach_pct"),
           "at_least_one_complete_bid_and_ask_band":trusted,
           "bands":{}}
        reach=raw.get("reach_pct") or {}
        for band in BANDS:
            r=(raw.get("bands") or {}).get(band) or {}
            status=checks[band].get("status","unavailable")
            actually_complete=(status=="usable" and
                               r.get("bid_coverage_complete") is True and
                               r.get("ask_coverage_complete") is True)
            if status=="usable" and not actually_complete:
                raise ValueError("per-metric gate marks incomplete original depth as usable: "+name+"."+band)
            if actually_complete:
                perband[band]["usable_count"]+=1
            else:
                perband[band]["missing_venues"].append(name)
            # Insufficient bid/ask reach is an explicit known limitation of
            # the SAME selected market, not a missing global exchange.
            detail["bands"][band]={
                "status":"usable" if actually_complete else status,
                "both_sides_complete":actually_complete,
                "bid_coverage_complete":r.get("bid_coverage_complete") is True,
                "ask_coverage_complete":r.get("ask_coverage_complete") is True,
                "reason":None if actually_complete else
                    "original_snapshot_does_not_cover_both_sides_of_this_price_band",
                "bid_reach_pct":reach.get("bid"),
                "ask_reach_pct":reach.get("ask")}
        markets[name]=detail
    expected_total=len(BOOKS)
    live={
        "expected_named_markets":expected_total,
        "verified_markets":sum(m["at_least_one_complete_bid_and_ask_band"] for m in markets.values()),
        "all_selected_venues_available_at_narrow_observed_depth":
           sum(m["at_least_one_complete_bid_and_ask_band"] for m in markets.values())==expected_total,
        "same_instrument_no_substitution":True,
        "market_details":markets,
        "complete_bid_ask_bands":perband,
        "all_11_verified_at_1pct":perband["1.0"]["usable_count"]==expected_total,
        "one_percent_limit_is_not_zero_liquidity":True,
        "source_documentation":{
           "bybit_full_book":"https://bybit-exchange.github.io/docs/v5/market/full-ob",
           "binance_usdm_max_1000":"https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/websocket-api",
           "bitget_max_1000":"https://www.bitget.com/docs/catalog/market/market-data",
           "okx_books_max_400":"https://www.okx.com/docs-v5/en/",
           "gate_futures":"https://www.gate.com/docs/developers/apiv4/en/futures/"},
        "official_deeper_snapshot_probe":{
          "probe_utc":deep.get("probe_at_utc"),
          "bybit_spot_full_http_code":(deep.get("markets") or {}).get("bybit_spot_full",{}).get("http_error_code"),
          "bybit_perpetual_full_http_code":(deep.get("markets") or {}).get("bybit_usdt_perp_full",{}).get("http_error_code"),
          "gate_300_result":(deep.get("markets") or {}).get("gate_usdt_perp_300",{}).get("status"),
          "gate_300_levels_each_side":(
              (deep.get("markets") or {}).get("gate_usdt_perp_300",{}).get("bid_count"),
              (deep.get("markets") or {}).get("gate_usdt_perp_300",{}).get("ask_count")),
          "official_only_no_403_workarounds":True,
          "do_not_repeat_failed_403_queries_every_hour":True}}
    x["live_orderbook"]=live
    details={}
    delayed=0
    alternative_usable=0
    for primary,alt in COST_BASIS.items():
        original=(original_onchain.get("latest") or {}).get(primary) or {}
        check=quality.get("onchain.market_onchain."+primary) or {}
        alternative=(brief.get("onchain_cost_basis_independent") or {}).get(alt) or {}
        if check.get("status")=="usable" and (original.get("status") not in ("fresh","usable","ok") or
                original.get("value") is None):
            raise ValueError("original onchain cost basis was falsely promoted to fresh: "+primary)
        is_delayed=check.get("status")!="usable"
        if is_delayed:delayed+=1
        if alternative.get("status")=="usable":alternative_usable+=1
        details[primary]={
          "original_source":"BGeometrics bitcoin-data.com",
          "original_value":original.get("value") if not is_delayed else None,
          "latest_observation_date":original.get("date"),
          "original_status":check.get("status","unavailable"),
          "unusable_reason":"original_vendor_measurement_delayed_not_a_collector_error" if is_delayed else None,
          "original_last_reported_even_if_stale":original.get("value") if is_delayed else None,
          "genuinely_independent_alternative":{
            "source":"Bitview", "name":alt,"status":alternative.get("status"),
            "observation_date":alternative.get("date"),"value":alternative.get("value"),
            "methodology":alternative.get("methodology"),
            "never_interchangeable_with_original_155d_entity_weighted_cohorts":
                alt!="network_realized_price",
            "use_as_distinct_context_only":True}}
    x["onchain_cost_basis"]={
        "original_series":details,
        "delayed_original_count":delayed,
        "separate_independent_alternatives_current":alternative_usable,
        "original_data_lag_not_equal_missing_market_signal":True,
        "do_not_backfill_or_relabel_original_keys_using_150d_UTXO":True}
    hist={}
    for name,j,clock in (
       ("hft_11_13_utc",hft,"11-13 UTC sourced checkpoint; not continuous"),
       ("bybit_00_utc",bybit,"first genuine 00 UTC snapshot; not daily mean")):
        coverage=j.get("coverage") or {}
        recent=j.get("recent") or {}
        hist[name]={
            "generated_utc":j.get("generated_at"),
            "target_day":j.get("target_anchor_date") or j.get("target_day"),
            "verification_clock":clock,
            "market_verified_days":{
                k:v.get("verified_days") for k,v in coverage.items() if isinstance(v,dict)},
            "recent_30d_by_market":{
                k:{"eligible_days":v.get("eligible_days"),"verified_days":v.get("verified_days"),
                   "same_clock_verified_days":v.get("same_clock_12utc_verified_days")}
                for k,v in (recent.get("30d") or {}).items() if isinstance(v,dict)} if name=="hft_11_13_utc" else None,
            "recent_source_error_count":len(j.get("errors_recent_run") or []),
            "continuous_level2_reconstruction_claimed":False,
            "backfill_owned_by_separate_existing_automation":True}
    x["historical_L2"]=hist
    x["resolution_summary"]={
        "all_11_live_markets_working":live["all_selected_venues_available_at_narrow_observed_depth"],
        "all_11_complete_at_1pct":live["all_11_verified_at_1pct"],
        "source_depth_limited_bands":sum(len(v["missing_venues"]) for v in perband.values()),
        "original_onchain_series_delayed":delayed,
        "independent_methodology_alternatives_available":alternative_usable,
        "remaining_gaps_explicit_and_not_silently_filled":True,
        "historical_backfill_not_restarted_or_modified":True,
        "no_global_market_exhaustiveness_claim":True,
        "classification":
            "usable_selected_markets_with_documented_irreducible_source_limits"
            if live["all_selected_venues_available_at_narrow_observed_depth"] else
            "selected_markets_require_recovery"}
    return x

def main():
    brief=load(ROOT/"brief.json")
    source=load("btc-liquidity/data/latest.json")
    onchain=load("btc-onchain/data/latest.json")
    hft=load("btc-liquidity/data/hft_latest.json")
    bybit=load("btc-liquidity/data/bybit_independent_latest.json")
    deep=load("btc-liquidity/data/deep_book_probe.json")
    if not brief.get("metric_quality") or not source.get("current"):
        raise SystemExit("Missing original evidence; cannot certify actual source coverage")
    report=build(brief,source,onchain,hft,bybit,deep)
    target=ROOT/"coverage_latest.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(json.dumps({"at":report["assembled_at_utc"],
          "live_by_band":report["live_orderbook"]["complete_bid_ask_bands"],
          "delayed_original_onchain":report["onchain_cost_basis"]["delayed_original_count"],
          "alternatives":report["onchain_cost_basis"]["separate_independent_alternatives_current"],
          "resolution":report["resolution_summary"]},ensure_ascii=False))
if __name__=="__main__":main()
