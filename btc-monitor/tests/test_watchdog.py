"""Offline regression tests for real BTC collector watchdog decisions."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

SPEC = importlib.util.spec_from_file_location(
    "btc_watchdog", Path(__file__).resolve().parents[1] / "watchdog.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 2, 19, 45, tzinfo=UTC)


def cvd_data(generated="2026-11-02T19:35:00Z",
             observed_hour="2026-11-02T17:00:00Z"):
    return {"generated_utc": generated, "last_complete_hour": observed_hour,
            "windows": {"1h": {"complete": True},
                        "24h": {"complete": False},
                        "168h": {"complete": False},
                        "720h": {"complete": False}}}


class WatchdogTests(unittest.TestCase):
    def test_recent_complete_hour_with_incomplete_coinbase_is_not_outage(self):
        v = m.assess("spot_cvd", cvd_data(), NOW)
        self.assertEqual(v["status"], "healthy")
        self.assertFalse(v["needs_recovery"])
        self.assertIn("five_venue_cvd_24h_incomplete", v["coverage_gaps"])

    def test_new_source_file_with_missing_latest_spot_hour_triggers_recovery(self):
        sample=cvd_data()
        sample["windows"]["1h"]={"complete":False,"net":None}
        result=m.assess("spot_cvd",sample,NOW)
        self.assertTrue(result["needs_recovery"])
        self.assertEqual(result["reason"],"newest_spot_cvd_hour_missing_executed_trades")
        self.assertIn("five_venue_cvd_1h_incomplete",result["coverage_gaps"])

    def test_old_complete_hour_even_with_fresh_json_is_outage(self):
        v = m.assess("spot_cvd", cvd_data(observed_hour="2026-11-02T10:00:00Z"), NOW)
        self.assertEqual(v["status"], "stale_observation")
        self.assertTrue(v["needs_recovery"])

    def test_price_usable_closed_candle_does_not_make_old_quote_live(self):
        p = {"generated_utc": "2026-11-02T19:30:00Z",
             "last_closed_day_utc": "2026-11-01",
             "last_closed_week_monday_utc": "2026-10-26",
             "spot_quote": {"price_usdt": 77500,
                            "observed_utc": "2026-11-02T12:30:00Z"}}
        v = m.assess("price_technical", p, NOW)
        self.assertTrue(v["closed_candles_valid"])
        self.assertEqual(v["status"], "stale_observation")
        self.assertEqual(v["reason"], "live_quote_stale")

    def test_daily_bitview_observation_lag_repaired_only_beyond_normal_lag(self):
        good = {"generated_utc":"2026-11-02T15:00:00Z",
                "last_closed_utc_day":"2026-11-01",
                "latest":{"lth_supply_150d":{"date":"2026-11-01","value":12345}}}
        result = m.assess("onchain_bitview",good,NOW)
        self.assertEqual(result["status"],"healthy")
        bad = dict(good,last_closed_utc_day="2026-10-22")
        result = m.assess("onchain_bitview",bad,NOW)
        self.assertEqual(result["reason"],"bitview_holder_series_lag_gt_3d")
        self.assertTrue(result["needs_recovery"])

    def test_onchain_vendor_delays_visible_but_no_duplicate_retry(self):
        value = {"generated_utc":"2026-11-02T15:00:00Z",
                 "latest":{"mvrv":{"status":"fresh","date":"2026-11-01","value":1.2},
                           "sth_realized_price":{"status":"delayed","date":"2026-10-26","value":None}}}
        result = m.assess("onchain_market",value,NOW)
        self.assertEqual(result["status"],"healthy")
        self.assertIn("sth_realized_price:missing_or_vendor_delay",result["coverage_gaps"])

    def test_critical_onchain_vendor_delay_is_degraded_not_healthy_or_retry(self):
        value={"generated_utc":"2026-11-02T15:00:00Z",
               "latest":{"mvrv":{"status":"delayed","date":"2026-10-29","value":1.3},
                         "sth_sopr":{"status":"delayed","date":"2026-10-29","value":1.1},
                         "lth_realized_profit":{"status":"fresh","date":"2026-11-01","value":100}}}
        result=m.assess("onchain_market",value,NOW)
        self.assertEqual(result["status"],"degraded_vendor_observations")
        self.assertFalse(result["needs_recovery"])
        self.assertEqual(set(result["delayed_important_metrics"]),{"mvrv","sth_sopr"})
        self.assertIn("mvrv:missing_or_vendor_delay",result["coverage_gaps"])

    def test_whale_alerts_no_latest_event_does_not_mean_collector_failed(self):
        value = {"generated_utc":"2026-11-02T15:00:00Z",
                 "labelled_to_exchange_alerts":7225,
                 "last_observed_day":"2026-11-01"}
        result = m.assess("onchain_whale_alerts",value,NOW)
        self.assertFalse(result["needs_recovery"])

    def test_missing_price_after_new_day(self):
        v = m.assess("price_technical", {
            "generated_utc": "2026-11-03T00:50:00Z",
            "last_closed_day_utc": "2026-11-01",
            "last_closed_week_monday_utc": "2026-10-26",
            "spot_quote": {"price_usdt": 77400,
                           "observed_utc": "2026-11-03T00:49:00Z"}},
            dt.datetime(2026, 11, 3, 1, 0, tzinfo=UTC))
        self.assertFalse(v["closed_candles_valid"])
        self.assertTrue(v["needs_recovery"])

    def test_healthy_macro_and_etf_during_reporting_lag(self):
        v = m.assess("macro_etf", {
            "generated_utc": "2026-11-02T19:35:00Z",
            "status": "ok", "etf": {"status": "usable",
                                   "date": "2026-10-30"}}, NOW)
        self.assertEqual(v["status"], "healthy")
        self.assertFalse(v["needs_recovery"])
        self.assertEqual(v["coverage_gaps"], [])

    def test_partial_macro_is_visible_without_disabling_all(self):
        v = m.assess("macro_etf", {
            "generated_utc": "2026-11-02T19:35:00Z",
            "status": "partial", "etf": {"status": "unavailable"}}, NOW)
        self.assertEqual(v["status"], "healthy")
        self.assertIn("partial_macro_source", v["coverage_gaps"])
        self.assertIn("etf_flow_unusable_or_reporting_lag", v["coverage_gaps"])

    def test_full_eleven_live_books_are_verified_by_market_not_fresh_json(self):
        book={"bid_coverage_complete":True,"ask_coverage_complete":True,
              "bid_usd":1000,"ask_usd":800}
        markets={}
        for venue,market in m.LIVE_BOOK_MARKETS.items():
            transport=("binance_official_ws_api_depth" if venue=="binance_usdm_perp"
                else "bybit_official_ws_snapshot" if venue in m.WS_REQUIRED
                else "official_public_rest")
            markets[venue]={"market":market,"captured_at":"2026-11-02T19:35:00Z",
                            "source_timestamp":"2026-11-02T19:34:59Z"
                                if venue in m.WS_REQUIRED or venue in m.NATIVE_TIME_REQUIRED else None,
                            "transport":transport,"bands":{"0.01":book}}
        source={"generated_at":"2026-11-02T19:35:00Z","errors":[],
                "spot_usable_venues":6,"perpetual_usable_venues":5,
                "current":{"venues":markets}}
        value=m.assess("live_depth",source,NOW)
        self.assertEqual(value["status"],"healthy")
        self.assertFalse(value["needs_recovery"])
        self.assertEqual(value["selected_markets_verified"],11)
        self.assertEqual(value["verified_spot_markets"],6)
        self.assertEqual(value["verified_perpetual_markets"],5)
        # A silently absent Binance perpetual must not be reported healthy
        # simply because ten other venues published fresh books.
        del markets["binance_usdm_perp"]
        failure=m.assess("live_depth",source,NOW)
        self.assertTrue(failure["needs_recovery"])
        self.assertEqual(failure["selected_markets_verified"],10)
        self.assertIn("live_orderbook:binance_usdm_perp:missing",failure["coverage_gaps"])

    def test_live_book_stale_bybit_exchange_timestamp_triggers_recovery(self):
        source={"generated_at":"2026-11-02T19:35:00Z",
                "current":{"venues":{"bybit_spot":{
                    "market":"spot","transport":"bybit_official_ws_snapshot",
                    "captured_at":"2026-11-02T19:35:00Z",
                    "source_timestamp":"2026-11-02T15:00:00Z",
                    "bands":{"0.01":{"bid_coverage_complete":True,
                                       "ask_coverage_complete":True}}}}}}
        failure=m.assess("live_depth",source,NOW)
        self.assertEqual(failure["market_health"]["bybit_spot"],"stale_native_source_timestamp")
        self.assertTrue(failure["needs_recovery"])

    def test_stale_historical_L2_is_external_only(self):
        v = m.assess("hft_depth", {
            "generated_at": "2026-11-02T18:30:00Z",
            "target_anchor_date": "2026-10-24", "status": "ok"}, NOW)
        self.assertTrue(v["needs_recovery"])
        self.assertEqual(v["recovery_policy"], "separate_existing_L2_backfill_only")
        decision = m.recovery_decision("hft_depth", v, {}, {}, NOW, 2)
        self.assertEqual(decision["action"], "observe_only")

    def test_skipped_workflow_not_counted_as_success(self):
        sample = [
            {"status": "completed", "conclusion": "skipped", "id": 8},
            {"status": "completed", "conclusion": "failure", "id": 7},
            {"status": "completed", "conclusion": "success", "id": 6},
        ]
        old_api = m.api
        try:
            m.api = lambda method, path, payload=None: {"workflow_runs": sample}
            x = m.latest_workflow_run("btc-price-technicals.yml")
        finally:
            m.api = old_api
        self.assertEqual(x["ignored_skipped_cancelled"], 1)
        self.assertEqual(x["latest"]["id"], 7)
        self.assertEqual(x["completed"]["conclusion"], "failure")

    def test_existing_running_workflow_prevents_duplicate_dispatch(self):
        r = {"needs_recovery": True, "reason": "stale_data"}
        workflow = {"active": {"id": 1234, "created_at": NOW.isoformat()}}
        state = {}
        decision = m.recovery_decision("spot_cvd", r, workflow, state, NOW, 2)
        self.assertEqual(decision["action"], "waiting_existing_run")

    def test_two_hour_cooldown_and_24_hour_retry_limit(self):
        r = {"needs_recovery": True, "reason": "stale_data"}
        state = {"sources": {"spot_cvd": {"dispatched_utc": [
            (NOW-dt.timedelta(minutes=20)).isoformat()]}}}
        self.assertEqual(m.recovery_decision("spot_cvd", r, {}, state, NOW, 2)
                         ["action"], "cooldown")
        state["sources"]["spot_cvd"]["dispatched_utc"] = [
            (NOW-dt.timedelta(hours=i*3)).isoformat() for i in range(3)]
        self.assertEqual(m.recovery_decision("spot_cvd", r, {}, state, NOW, 2)
                         ["action"], "exhausted")

    def test_dispatch_is_bounded_and_state_is_committed_only_after_success(self):
        r = {"needs_recovery": True, "reason": "missing_file"}
        state = {}
        calls = []
        def dispatch(method, path, payload):
            calls.append((method, path, payload))
            return {}
        got = m.recovery_decision("price_technical", r, {}, state, NOW, 1,
                                  dispatch_fn=dispatch)
        self.assertEqual(got["action"], "dispatched")
        self.assertEqual(len(state["sources"]["price_technical"]["dispatched_utc"]), 1)
        self.assertEqual(calls[0][2], {"ref": "main"})
        self.assertEqual(
            m.recovery_decision("derivatives", r, {}, state, NOW, 0,
                                dispatch_fn=dispatch)["action"], "deferred")
        self.assertEqual(len(calls), 1)

    def test_dispatch_failure_does_not_spend_retry_budget(self):
        r = {"needs_recovery": True, "reason": "missing_file"}
        state = {}
        def fail(*args):
            raise RuntimeError("GitHub_HTTP_403")
        got = m.recovery_decision("options", r, {}, state, NOW, 2,
                                  dispatch_fn=fail)
        self.assertEqual(got["action"], "dispatch_failed")
        self.assertEqual(state["sources"]["options"]["dispatched_utc"], [])

    def test_stale_generated_macro_is_not_validated_by_old_FRED_date(self):
        v = m.assess("macro_etf", {
            "generated_utc": "2026-11-02T10:07:00Z",
            "etf": {"status": "usable", "date": "2026-10-30"}}, NOW)
        self.assertEqual(v["status"], "stale_file")
        self.assertTrue(v["needs_recovery"])



    def test_fresh_monitor_bridge_cannot_hide_required_stale_inputs(self):
        source={k:{"status":"fresh"} for k in
                ("price_technical","spot_cvd","derivatives","options",
                 "macro_etf","live_depth","onchain")}
        record={"as_of_utc":NOW.isoformat(),"coverage_gaps":[],
                "sources":source,"family_readiness":{"price_technical_verified":True},
                "metric_quality":{"checks":{"price.closed_daily_weekly":{"status":"usable"}},
                                  "critical_issues":[]}}
        ok=m.assess("monitor_bridge",record,NOW)
        self.assertEqual(ok["status"],"healthy")
        self.assertFalse(ok["needs_recovery"])
        record["metric_quality"]["critical_issues"]=["spot_cvd.original_five.24h:incomplete"]
        result=m.assess("monitor_bridge",record,NOW)
        self.assertEqual(result["status"],"degraded_critical_inputs")
        self.assertFalse(result["needs_recovery"])  # no useless bridge retry
        self.assertTrue(result["critical_metric_issues"])
        self.assertIn("critical_metric:spot_cvd.original_five.24h:incomplete",result["coverage_gaps"])
        record["metric_quality"]["critical_issues"]=[]
        record["sources"]["spot_cvd"]["status"]="stale"
        bad=m.assess("monitor_bridge",record,NOW)
        self.assertEqual(bad["status"],"degraded_critical_inputs")
        self.assertIn("spot_cvd",bad["stale_or_missing_critical_families"])
        self.assertFalse(bad["needs_recovery"])

    def test_bridge_absent_metric_quality_requires_real_rebuild(self):
        record={"as_of_utc":NOW.isoformat(),
                "sources":{"spot_cvd":{"status":"fresh"}},
                "family_readiness":{},
                "metric_quality":{"checks":{}}}
        bad=m.assess("monitor_bridge",record,NOW)
        self.assertEqual(bad["status"],"invalid_schema")
        self.assertEqual(bad["reason"],"bridge_metric_quality_missing")
        self.assertTrue(bad["needs_recovery"])

    def test_stale_native_okx_gate_and_bitget_snapshots_not_laundered(self):
        book={"bid_coverage_complete":True,"ask_coverage_complete":True,
              "bid_usd":120000,"ask_usd":145000}
        for market in m.NATIVE_TIME_REQUIRED:
            source={"generated_at":NOW.isoformat(),"errors":[],
                    "current":{"venues":{market:{
                        "market":m.LIVE_BOOK_MARKETS[market],
                        "captured_at":NOW.isoformat(),
                        "source_timestamp":"2026-11-02T14:00:00Z",
                        "transport":"official_public_rest",
                        "bands":{"0.01":book}}}}}
            if market=="gate_usdt_perp":
                source["current"]["venues"][market]["transport"]="gate_official_ws_v2_full_snapshot"
            result=m.assess("live_depth",source,NOW)
            self.assertEqual(result["market_health"][market],
                             "stale_native_source_timestamp",market)
            self.assertTrue(result["needs_recovery"])
        # One unverified book must not be counted as healthy or repair itself
        # by selecting an unrelated venue's newest timestamp.

if __name__ == "__main__":
    unittest.main()
