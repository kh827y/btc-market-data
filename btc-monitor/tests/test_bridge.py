import datetime as dt
import importlib.util
import pathlib
import unittest

path=pathlib.Path(__file__).resolve().parents[1]/"build_feed.py"
spec=importlib.util.spec_from_file_location("btc_bridge",path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
UTC=dt.timezone.utc
NOW=dt.datetime(2026,11,2,7,30,tzinfo=UTC)

class BridgeTests(unittest.TestCase):
 def test_stale_not_laundered_by_new_bridge(self):
  o=m.build({"spot_cvd":{"generated_utc":"2026-11-01T07:00:00Z","windows":{"1h":{"complete":True,"net":1}}}},NOW)
  self.assertEqual(o["feeds"]["spot_cvd"]["status"],"stale")
  self.assertFalse(o["audit"]["family_readiness"]["spot_execution"])
 def test_spot_cvd_missing_window_does_not_fabricate(self):
  s={"generated_utc":"2026-11-02T07:10:00Z",
     "windows":{"1h":{"complete":True,"net":30},
                "24h":{"complete":False,"net":9999}}}
  o=m.build({"spot_cvd":s},NOW)
  self.assertEqual(o["metrics"]["spot_cvd"]["windows"]["1h"]["net_usd_approx"],30)
  self.assertIsNone(o["metrics"]["spot_cvd"]["windows"]["24h"]["net_usd_approx"])
  self.assertFalse(o["audit"]["family_readiness"]["spot_cvd_24h_complete"])
 def test_unreached_depth_is_null(self):
  bands={"0.2":{"bid_coverage_complete":True,"ask_coverage_complete":False,
                "bid_usd":100,"ask_usd":0,"imbalance_bid_share":1},
         "0.01":{"bid_coverage_complete":True,"ask_coverage_complete":True,
                 "bid_usd":100,"ask_usd":50,"imbalance_bid_share":0.666}}
  b=m.guard_bands(bands)
  self.assertIsNone(b["0.2"]["bid_usd"])
  self.assertFalse(b["0.2"]["complete"])
  self.assertEqual(b["0.01"]["ask_usd"],50)
 def test_historical_is_separate_and_not_current_depth(self):
  data={"generated_at":"2026-11-02T07:11:00Z","status":"ok",
        "comparison":{"binance_spot":{"latest_day":"2026-11-01","previous_days":{"7d":{"bands":{"0.05":{"bid_change_pct":-9}}}}}}}
  o=m.build({"hft_depth":data},NOW)
  self.assertTrue(o["audit"]["family_readiness"]["orderbook"])
  self.assertFalse(o["audit"]["family_readiness"]["current_orderbook"])
 def test_onchain_missing_value_never_becomes_zero(self):
  data={"generated_utc":"2026-11-02T06:10:00Z","components":{"market_onchain":{"latest":{"mvrv":{"status":"missing","value":None,"date":None}}}}}
  o=m.build({"onchain":data},NOW)
  self.assertIsNone(o["metrics"]["onchain"]["groups"]["market_onchain"]["metrics"]["mvrv"]["value"])
 def test_future_source_time_rejected(self):
  o=m.build({"options":{"generated_utc":"2026-11-03T07:30:00Z"}},NOW)
  self.assertEqual(o["feeds"]["options"]["status"],"future_timestamp")

 def test_source_verified_scoped_cvd_never_becomes_global_total(self):
  bands={"binance":{"complete":True,"hours":24,"required":24,"net":100},
         "okx":{"complete":True,"hours":24,"required":24,"net":-20},
         "bybit":{"complete":True,"hours":24,"required":24,"net":30},
         "coinbase":{"complete":False,"hours":2,"required":24,"net":None},
         "kraken":{"complete":False,"hours":0,"required":24,"net":None}}
  row={"complete":False,"net":None,"by_venue":bands,
       "complete_venue_subset":{"available":True,"venues":["binance","okx","bybit"],
                                "net":110,"venue_count":3}}
  out=m.build({"spot_cvd":{"generated_utc":"2026-11-02T07:15:00Z",
                            "windows":{"24h":row}}},NOW)
  res=out["metrics"]["spot_cvd"]["windows"]["24h"]
  self.assertIsNone(res["net_usd_approx"])
  self.assertEqual(res["complete_venue_subset"]["net_usd_approx"],110)
  self.assertFalse(out["audit"]["family_readiness"]["spot_cvd_24h_complete"])
  self.assertTrue(out["audit"]["family_readiness"]["spot_cvd_24h_covered_subset"])
  self.assertEqual(m.make_brief(out)["spot_cvd"]["windows"]["24h"]["complete_venue_subset"]["venue_count"],3)
 def test_reject_fabricated_complete_venue_subset(self):
  bogus={"generated_utc":"2026-11-02T07:15:00Z",
         "windows":{"24h":{"complete":False,"net":None,
                   "by_venue":{"binance":{"complete":False,"net":None}},
                   "complete_venue_subset":{"available":True,"venues":["binance","coinbase","bybit"],"net":9999}}}}
  report=m.build({"spot_cvd":bogus},NOW)
  self.assertFalse(report["metrics"]["spot_cvd"]["windows"]["24h"]["complete_venue_subset"]["available"])
  self.assertIsNone(report["metrics"]["spot_cvd"]["windows"]["24h"]["complete_venue_subset"]["net_usd_approx"])

 def test_fresh_json_with_old_spot_observation_is_rejected(self):
  source={"generated_utc":"2026-11-02T07:25:00Z",
          "last_complete_hour":"2026-11-01T18:00:00Z",
          "windows":{"1h":{"complete":True,"net":100}}}
  out=m.build({"spot_cvd":source},NOW)
  self.assertEqual(out["feeds"]["spot_cvd"]["status"],"stale_observation")
  self.assertNotIn("spot_cvd",m.make_brief(out))
  self.assertFalse(out["audit"]["family_readiness"]["spot_execution"])

 def test_actual_cme_recent_observed_basis_is_visible(self):
  source={"generated_utc":"2026-11-02T07:15:00Z","results":{
   "cme_basis":{"status":"recent_observed",
     "front_recent_contract":{"date":"2026-10-30","contract":"BTCZ26.CME","annualized_basis_pct":2.99}}}}
  out=m.build({"derivatives":source},NOW)
  front=out["metrics"]["derivatives"]["cme_front_basis"]
  self.assertEqual(front["contract"],"BTCZ26.CME")
  self.assertEqual(m.make_brief(out)["derivatives"]["cme_front_basis"]["annualized_basis_pct"],2.99)
  self.assertNotIn("derivatives:cme_front_basis_unavailable",out["audit"]["coverage_gaps"])

 def test_coverage_gaps_report_incomplete_cvd_and_failed_venues(self):
  src={"spot_cvd":{"generated_utc":"2026-11-02T07:15:00Z",
             "last_complete_hour":"2026-11-02T06:00:00Z",
             "windows":{"24h":{"complete":False,"net":None}}},
       "live_depth":{"generated_at":"2026-11-02T07:20:00Z",
                     "status":"ok","errors":["venue1 failed","venue2 failed"],
                     "current":{"venues":{}}},
       "onchain":{"generated_utc":"2026-11-02T07:15:00Z",
                  "components":{}}}
  out=m.build(src,NOW)
  gaps=out["audit"]["coverage_gaps"]
  self.assertIn("spot_cvd:24h_five_venue_incomplete",gaps)
  self.assertIn("live_depth:failed_venues=2",gaps)
  self.assertTrue(any(x.startswith("onchain:missing_or_delayed_metrics=") for x in gaps))
  brief=m.make_brief(out)
  self.assertEqual(brief["sources"]["live_depth"]["source_errors"],2)
  self.assertEqual(brief["sources"]["spot_cvd"]["measurement_age_h"],1.5)
  self.assertEqual(brief["coverage_gaps"],gaps)

 def test_zero_bid_share_is_retained(self):
  got=m.guard_bands({"0.05":{"bid_coverage_complete":True,"ask_coverage_complete":True,
                           "bid_share":0.0,"imbalance_bid_share":0.7}})
  self.assertEqual(got["0.05"]["bid_share"],0.0)

 def test_fixed_five_spot_scope_separate_from_original_coinbase_five(self):
  originals=["binance","coinbase","okx","bybit","kraken"]
  alt=["binance","okx","bybit","kraken","bitget"]
  row={"complete":False,"net":None,
       "by_venue":{v:{"complete":v!="coinbase","hours":24 if v!="coinbase" else 4,
                      "required":24,"net":10 if v!="coinbase" else None}
                   for v in originals+["bitget"]},
       "fixed_five_ex_coinbase":{"complete":True,"venues":alt,"net":50},
       "complete_venue_subset":{"available":True,"venues":alt,"net":50}}
  source={"generated_utc":"2026-11-02T07:20:00Z",
          "last_complete_hour":"2026-11-02T06:00:00Z",
          "windows":{"24h":row}}
  result=m.build({"spot_cvd":source},NOW)
  full=result["metrics"]["spot_cvd"]["windows"]["24h"]
  self.assertFalse(full["complete"])
  self.assertIsNone(full["net_usd_approx"])
  self.assertTrue(full["fixed_five_ex_coinbase"]["complete"])
  self.assertEqual(full["fixed_five_ex_coinbase"]["net_usd_approx"],50)
  self.assertFalse(result["audit"]["family_readiness"]["spot_cvd_24h_complete"])
  self.assertTrue(result["audit"]["family_readiness"]["spot_cvd_24h_fixed_five_ex_coinbase"])
  self.assertEqual(m.make_brief(result)["spot_cvd"]["windows"]["24h"]["fixed_five_ex_coinbase"]["venues"],alt)
 def test_reject_unsubstantiated_fixed_five(self):
  row={"complete":False,"net":None,"by_venue":{"bitget":{"complete":False}},
       "fixed_five_ex_coinbase":{"complete":True,
                                 "venues":["binance","okx","bybit","kraken","bitget"],"net":9000}}
  result=m.build({"spot_cvd":{"generated_utc":"2026-11-02T07:20:00Z",
             "last_complete_hour":"2026-11-02T06:00:00Z","windows":{"24h":row}}},NOW)
  self.assertFalse(result["metrics"]["spot_cvd"]["windows"]["24h"]["fixed_five_ex_coinbase"]["complete"])

if __name__=="__main__":unittest.main()
