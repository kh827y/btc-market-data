"""Item 5 source-limit coverage ledger acceptance tests (stdlib, offline)."""
import datetime as dt
import importlib.util
from pathlib import Path
from copy import deepcopy
import unittest

path=Path(__file__).resolve().parents[1]/"coverage_audit.py"
spec=importlib.util.spec_from_file_location("btc_coverage",path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fixture():
    now="2026-11-02T21:04:00Z"
    v={}
    checks={}
    for venue,market in m.BOOKS.items():
        bands={}
        for band in m.BANDS:
            complete=band!="1.0"
            bands[band]={"bid_coverage_complete":complete,
                        "ask_coverage_complete":complete,
                        "bid_usd":100000 if complete else None,
                        "ask_usd":200000 if complete else None}
            checks["live_depth."+venue+"."+band]={"status":"usable" if complete else "incomplete"}
        checks["live_depth."+venue]={"status":"usable"}
        v[venue]={"market":market,"symbol":"BTCUSD" if venue=="coinbase_spot" else "BTCUSDT",
                  "captured_at":now,"reach_pct":{"bid":0.31,"ask":0.27},
                  "levels":{"bid":300,"ask":300},"bands":bands}
    for name in m.COST_BASIS:
        checks["onchain.market_onchain."+name]={"status":"stale"}
    brief={"as_of_utc":now,"metric_quality":{"checks":checks},
           "onchain_cost_basis_independent":{
              val:{"status":"usable","date":"2026-11-01","value":54000,
                   "methodology":"utxo_150d_independent"} for val in m.COST_BASIS.values()}}
    original_onchain={"latest":{
        name:{"date":"2026-10-26","value":50000,"status":"delayed"} for name in m.COST_BASIS}}
    probe={"probe_at_utc":now,"markets":{
       "bybit_spot_full":{"http_error_code":403},
       "bybit_usdt_perp_full":{"http_error_code":403},
       "gate_usdt_perp_300":{"status":"verified_native_full_snapshot",
            "bid_count":300,"ask_count":300}}}
    return brief,{"current":{"venues":v}},original_onchain,{}, {},probe

class CoverageLedgerTests(unittest.TestCase):
    def test_missing_1pct_not_equal_missing_exchange(self):
        result=m.build(*fixture())
        x=result["live_orderbook"]
        self.assertEqual(x["verified_markets"],11)
        self.assertFalse(x["all_11_verified_at_1pct"])
        self.assertEqual(x["complete_bid_ask_bands"]["1.0"]["usable_count"],0)
        self.assertEqual(len(x["complete_bid_ask_bands"]["1.0"]["missing_venues"]),11)
        self.assertEqual(result["resolution_summary"]["source_depth_limited_bands"],11)

    def test_stale_original_vs_genuine_independent_utxo_150d(self):
        result=m.build(*fixture())
        r=result["onchain_cost_basis"]
        self.assertEqual(r["delayed_original_count"],3)
        self.assertEqual(r["separate_independent_alternatives_current"],3)
        for name,details in r["original_series"].items():
            self.assertIsNone(details["original_value"])
            self.assertEqual(details["latest_observation_date"],"2026-10-26")
            self.assertEqual(details["original_last_reported_even_if_stale"],50000)
            self.assertTrue(details["genuinely_independent_alternative"]["use_as_distinct_context_only"])

    def test_single_unverified_bid_side_never_full_depth(self):
        data=list(fixture())
        data[1]["current"]["venues"]["gate_usdt_perp"]["bands"]["0.2"]["bid_coverage_complete"]=False
        data[0]["metric_quality"]["checks"]["live_depth.gate_usdt_perp.0.2"]["status"]="incomplete"
        out=m.build(*data)
        self.assertFalse(out["live_orderbook"]["market_details"]["gate_usdt_perp"]["bands"]["0.2"]["both_sides_complete"])
        self.assertIn("gate_usdt_perp",out["live_orderbook"]["complete_bid_ask_bands"]["0.2"]["missing_venues"])

    def test_gate_rejects_usable_if_original_bid_uncovered(self):
        data=list(fixture())
        data[1]["current"]["venues"]["gate_usdt_perp"]["bands"]["0.2"]["bid_coverage_complete"]=False
        with self.assertRaisesRegex(ValueError,"incomplete original depth"):
            m.build(*data)

    def test_historical_l2_owned_externally_and_not_promoted_to_live(self):
        data=list(fixture())
        data[3]={"generated_at":"2026-11-02T17:00:00Z","target_anchor_date":"2026-11-01",
                 "errors_recent_run":["unanchored checkpoint"],
                 "coverage":{"bybit":{"verified_days":61}},
                 "recent":{"30d":{"bybit":{"eligible_days":30,"verified_days":30,
                           "same_clock_12utc_verified_days":30}}}}
        out=m.build(*data)
        self.assertEqual(out["historical_L2"]["hft_11_13_utc"]["recent_source_error_count"],1)
        self.assertEqual(out["historical_L2"]["hft_11_13_utc"]["market_verified_days"]["bybit"],61)
        self.assertFalse(out["historical_L2"]["hft_11_13_utc"]["continuous_level2_reconstruction_claimed"])
        self.assertTrue(out["historical_L2"]["hft_11_13_utc"]["backfill_owned_by_separate_existing_automation"])

if __name__=="__main__":unittest.main()
