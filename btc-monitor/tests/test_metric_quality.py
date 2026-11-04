"""Item 4: BTC metric-level actual measurement/date/scope integrity regressions.

No network, fabricated trading signals or assumption that a fresh JSON implies
that all metrics are fresh. Source status gates must be independently honored.
"""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from copy import deepcopy

spec=importlib.util.spec_from_file_location("btc_quality",Path(__file__).resolve().parents[1]/"metric_quality.py")
q=importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
NOW=dt.datetime(2026,11,2,20,43,tzinfo=dt.timezone.utc)

def fresh(*keys):
    return {k:{"status":"fresh"} for k in keys}

def cvd(hours=24):
    return {"generated_utc":"2026-11-02T20:40:00Z",
      "last_complete_hour":"2026-11-02T18:00:00Z",
      "coinbase_window_integrity":{"24h":{
          "all_hours_id_continuous_verified":True,
          "id_continuous_proof_hours":24,
          "coinbase_missing_hours_count":0}},
      "windows":{"24h":{"complete":True,"net":50,
         "by_venue":{n:{"hours":hours,"required":24,"complete":True,"net":10}
                    for n in q.ORIGINAL_SPOT}}}}

def metrics_cvd():
    return {"spot_cvd":{"windows":{"24h":{
         "complete":True,"net_usd_approx":50,
         "complete_venue_subset":{},
         "fixed_five_ex_coinbase":{}}}}}

def live():
    payload={}
    for n,market in q.EXPECTED_LIVE.items():
        t=q.WS_TRANSPORTS.get(n,"official_public_rest")
        payload[n]={"market":market,
            "symbol":"BTCUSD" if n=="coinbase_spot" else "BTCUSDT",
            "captured_at":"2026-11-02T20:41:00Z",
            "source_timestamp":"2026-11-02T20:40:58Z"
                if n in q.WS_TRANSPORTS or n in q.NATIVE_BOOK_TIMESTAMPS else None,
            "transport":t,"bands":{"0.01":{
                "bid_coverage_complete":True,"ask_coverage_complete":True,
                "bid_usd":1000,"ask_usd":1200,"imbalance_bid_share":0.454545}}}
    return payload

class QualityTests(unittest.TestCase):
    def test_completed_utc_week_is_usable_midweek_not_stale(self):
        now=dt.datetime(2026,11,4,1,20,tzinfo=dt.timezone.utc)
        p={"closed_candles_only":True,
           "last_closed_day_utc":"2026-11-03",
           "last_closed_week_monday_utc":"2026-10-26",
           "spot_quote_status":"fresh",
           "latest_spot_observed_utc":"2026-11-04T01:19:00Z"}
        report=q.assess({"price_technical":{}},fresh("price_technical"),
                        {"price_technical":p},now)
        self.assertEqual(report["checks"]["price.closed_daily_weekly"]["status"],"usable")
        p["last_closed_week_monday_utc"]="2026-11-02"  # unclosed week
        report=q.assess({"price_technical":{}},fresh("price_technical"),
                        {"price_technical":p},now)
        self.assertEqual(report["checks"]["price.closed_daily_weekly"]["status"],"invalid")

    def test_cvd_five_venue_real_arithmetic_proof(self):
        raw=cvd()
        transformed=metrics_cvd()
        result=q.assess({"spot_cvd":raw},fresh("spot_cvd"),transformed,NOW)
        row=result["checks"]["spot_cvd.original_five.24h"]
        self.assertEqual(row["status"],"usable")
        self.assertEqual(transformed["spot_cvd"]["windows"]["24h"]["net_usd_approx"],50)

    def test_cvd_mismatched_sum_quarantines_even_complete_true(self):
        raw=cvd()
        raw["windows"]["24h"]["net"]=1000000
        transformed=metrics_cvd()
        result=q.assess({"spot_cvd":raw},fresh("spot_cvd"),transformed,NOW)
        self.assertEqual(result["checks"]["spot_cvd.original_five.24h"]["status"],"invalid")
        self.assertFalse(transformed["spot_cvd"]["windows"]["24h"]["complete"])
        self.assertIsNone(transformed["spot_cvd"]["windows"]["24h"]["net_usd_approx"])

    def test_cvd_missing_history_proof_quarantines_fake_complete(self):
        raw=cvd()
        raw["coinbase_window_integrity"]["24h"]["id_continuous_proof_hours"]=12
        transformed=metrics_cvd()
        result=q.assess({"spot_cvd":raw},fresh("spot_cvd"),transformed,NOW)
        self.assertEqual(result["checks"]["spot_cvd.original_five.24h"]["status"],"incomplete")
        self.assertIsNone(transformed["spot_cvd"]["windows"]["24h"]["net_usd_approx"])

    def test_cvd_stale_file_not_rescued_by_complete_count(self):
        transformed=metrics_cvd()
        result=q.assess({"spot_cvd":cvd()},{"spot_cvd":{"status":"stale"}},transformed,NOW)
        self.assertEqual(result["checks"]["spot_cvd.original_five.24h"]["status"],"stale")
        self.assertIsNone(transformed["spot_cvd"]["windows"]["24h"]["net_usd_approx"])

    def test_live_all_11_with_valid_band_useable(self):
        src={"live_depth":{"current":{"venues":live()}}}
        transformed={"live_depth":{"venues":{n:{"market":v["market"],
            "bands":{"0.01":{"complete":True,"bid_usd":1000,"ask_usd":1200}}}
            for n,v in live().items()}}}
        result=q.assess(src,fresh("live_depth"),transformed,NOW)
        self.assertTrue(all(result["checks"]["live_depth."+n]["status"]=="usable"
                            for n in q.EXPECTED_LIVE))
        self.assertEqual(transformed["live_depth"]["spot_usable_venues"],6)
        self.assertEqual(transformed["live_depth"]["perp_usable_venues"],5)

    def test_live_wrong_native_timestamp_cannot_be_current(self):
        data=live()
        data["bybit_spot"]["source_timestamp"]="2026-11-02T18:00:00Z"
        transformed={"live_depth":{"venues":{"bybit_spot":{"market":"spot",
            "bands":{"0.01":{"complete":True,"bid_usd":1000}}}}}}
        result=q.assess({"live_depth":{"current":{"venues":data}}},
                        fresh("live_depth"),transformed,NOW)
        self.assertEqual(result["checks"]["live_depth.bybit_spot"]["status"],"incomplete")
        self.assertNotIn("bybit_spot",transformed["live_depth"]["venues"])

    def test_live_unsupported_wide_band_is_null_not_zero(self):
        src=live()
        src["bybit_usdt_perp"]["bands"]["1.0"]={
            "bid_coverage_complete":False,"ask_coverage_complete":False,
            "bid_usd":0,"ask_usd":0}
        transformed={"live_depth":{"venues":{"bybit_usdt_perp":{"market":"perpetual",
            "bands":{"1.0":{"complete":True,"bid_usd":0,"ask_usd":0}}}}}}
        result=q.assess({"live_depth":{"current":{"venues":src}}},
                        fresh("live_depth"),transformed,NOW)
        self.assertEqual(result["checks"]["live_depth.bybit_usdt_perp.1.0"]["status"],"incomplete")
        self.assertIsNone(transformed["live_depth"]["venues"]["bybit_usdt_perp"]["bands"]["1.0"]["bid_usd"])

    def test_options_invalid_rr25_sign_and_math_is_rejected(self):
        raw={"results":{"deribit_live_surface":{
              "as_of_utc":"2026-11-02T20:42:00Z",
              "term_structure":{"1M":{
                 "status":"available","quality":"standard",
                 "atm_iv_pct":39,"call25_iv_pct":42,"put25_iv_pct":44,
                 "rr25_call_minus_put_volpts":2,
                 "expiry_left":"2026-11-27T08:00:00Z",
                 "expiry_right":"2026-12-25T08:00:00Z"}}}}}
        transformed={"options":{"deribit_term":{"1M":raw["results"]["deribit_live_surface"]["term_structure"]["1M"]},
                                 "dvol":{}}}
        r=q.assess({"options":raw},fresh("options"),transformed,NOW)
        self.assertEqual(r["checks"]["options.deribit.1M"]["status"],"invalid")
        self.assertIsNone(transformed["options"]["deribit_term"]["1M"])

    def test_onchain_upstream_delayed_never_becomes_zero_or_usable(self):
        raw={"components":{"lth_sth_bitview":{"feed_age_hours":2,
              "latest":{"sth_realized_price_150d":{"date":"2026-11-01","value":72000,"status":"delayed"}}}}}
        v={"date":"2026-11-01","lag_days":1,"value":72000,"status":"usable"}
        transformed={"onchain":{"groups":{"lth_sth_bitview":{"metrics":{"sth_realized_price_150d":v}}},
             "cost_basis_independent":{"sth_cost_basis_150d":{
                 "value":72000,"status":"usable"}}}}
        r=q.assess({"onchain":raw},fresh("onchain"),transformed,NOW)
        self.assertEqual(r["checks"]["onchain.lth_sth_bitview.sth_realized_price_150d"]["status"],"unverified")
        self.assertIsNone(v["value"])
        self.assertIsNone(transformed["onchain"]["cost_basis_independent"]["sth_cost_basis_150d"]["value"])

    def test_old_historical_l2_snapshot_cannot_validate_1d_comparison(self):
        raw={"target_day":"2026-10-15","comparisons":{
          "bybit_independent_spot":{"latest":"2026-10-15",
             "comparisons":{"1d":{"bands":{"0.01":{
                 "bid_change_pct":20,"ask_change_pct":12,"bid_share_change_pp":4}},
                 "baseline_day":"2026-10-14","baseline_time":"2026-10-14T00:00:01Z",
                 "current_time":"2026-10-15T00:00:01Z"}}}}}
        transformed={"bybit_depth":{}}
        r=q.assess({"bybit_depth":raw},fresh("bybit_depth"),transformed,NOW)
        self.assertEqual(r["checks"]["bybit_depth.bybit_independent_spot.1d.0.01"]["status"],"stale")

    def test_same_market_wrong_time_of_day_l2_is_not_comparable(self):
        raw={"target_day":"2026-11-01","comparisons":{
          "bybit_independent_spot":{"latest":"2026-11-01",
             "comparisons":{"7d":{"bands":{"0.01":{
                 "bid_change_pct":20,"ask_change_pct":12,"bid_share_change_pp":4}},
                 "baseline_date":"2026-10-25","baseline_time":"2026-10-25T12:00:00Z",
                 "current_time":"2026-11-01T00:00:00Z"}}}}}
        r=q.assess({"bybit_depth":raw},fresh("bybit_depth"),{"bybit_depth":{}},NOW)
        self.assertEqual(r["checks"]["bybit_depth.bybit_independent_spot.7d.0.01"]["status"],"not_comparable")

    def test_funding_uses_venue_native_okx_contract_not_binance_symbol(self):
        item={"symbol":"BTC-USDT-SWAP","last":"2026-11-02T16:00:00Z",
              "count":90,"max_gap_hours":8,
              "latest_rate_8h":0.0001,"latest_raw_rate":0.0001}
        raw={"results":{"funding":{"OKX":item}}}
        t={"derivatives":{"funding_settled":{},"forced_liquidations_24h":{}}}
        r=q.assess({"derivatives":raw},fresh("derivatives"),t,NOW)
        self.assertEqual(r["checks"]["derivatives.funding_8h.OKX"]["status"],"usable")
        self.assertEqual(t["derivatives"]["funding_settled"]["OKX"]["rate_8h"],0.0001)
        item["symbol"]="BTCUSDT"
        bad=q.assess({"derivatives":raw},fresh("derivatives"),t,NOW)
        self.assertEqual(bad["checks"]["derivatives.funding_8h.OKX"]["status"],"invalid")

    def test_whole_file_recent_does_not_make_bad_oi_fresh(self):
        oi={"venues":["Binance","Bybit","OKX","Gate.io","Hyperliquid"],
            "unit":"USD notional (vendor normalized)","latest_hour":"2026-11-02T19:00:00Z",
            "latest_venue_usd":{"Binance":1e9,"Bybit":1e9,"OKX":1e9,"Gate.io":1e9,"Hyperliquid":1e9},
            "latest_five_venue_usd":10e9}
        transform={"derivatives":{"oi_five_venue_usd":10e9,"oi_1d_7d_30d_pct":{"7d":1},
              "funding_settled":{},"forced_liquidations_24h":{}}}
        r=q.assess({"derivatives":{"results":{"open_interest":oi}}},
                   fresh("derivatives"),transform,NOW)
        self.assertEqual(r["checks"]["derivatives.oi_five"]["status"],"invalid")
        self.assertIsNone(transform["derivatives"]["oi_five_venue_usd"])

    def test_fed_macro_source_does_not_swap_broad_usd_and_dxy(self):
        derived={"macro_etf":{"quality":{"fed_rates":True,"treasury_yields":True,
                            "usd_broad_index":True,"ice_dxy_exact":False,"spot_etf_flow":False},
                           "us_spot_bitcoin_etf":{"status":"missing_or_delayed"}}}
        r=q.assess({"macro_etf":{}},fresh("macro_etf"),derived,NOW)
        self.assertEqual(r["checks"]["macro.ice_dxy_exact"]["status"],"unverified")
        self.assertEqual(r["checks"]["macro.usd_broad_index"]["status"],"usable")


    def test_live_rest_native_timestamp_and_transport_fail_closed(self):
        for venue in q.NATIVE_BOOK_TIMESTAMPS:
            data=live()
            data[venue]["source_timestamp"]="2026-11-02T15:00:00Z"
            transformed={"live_depth":{"venues":{venue:{"market":q.EXPECTED_LIVE[venue],
                      "bands":{"0.01":{"complete":True,"bid_usd":1000,"ask_usd":1200}}}}}}
            r=q.assess({"live_depth":{"current":{"venues":data}}},
                       fresh("live_depth"),transformed,NOW)
            self.assertEqual(r["checks"]["live_depth."+venue]["status"],"incomplete",venue)
            self.assertNotIn(venue,transformed["live_depth"]["venues"])
        # Timestamp by itself is not enough: a data feed falsely labeled
        # as a native official source must also fail the provenance gate.
        data=live()
        data["gate_spot"]["transport"]="unverified_third_party_proxy"
        transformed={"live_depth":{"venues":{}}}
        r=q.assess({"live_depth":{"current":{"venues":data}}},
                   fresh("live_depth"),transformed,NOW)
        self.assertEqual(r["checks"]["live_depth.gate_spot"]["status"],"incomplete")

if __name__=="__main__":unittest.main()
