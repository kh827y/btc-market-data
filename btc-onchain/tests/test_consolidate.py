"""Reference-only vendor lag is not a live onchain outage.

No external requests: assert raw source dates and coverage accounting remain
transparent, while current-signal sources keep strict missing-data checks.
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

source=Path(__file__).resolve().parents[1]/"consolidate.py"
spec=importlib.util.spec_from_file_location("onchain_consolidate",source)
c=importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class ConsolidationReferenceTests(unittest.TestCase):
    def build(self, core_available=True):
        now=dt.datetime.now(dt.timezone.utc)
        recent=(now.date()-dt.timedelta(days=1)).isoformat()
        old=(now.date()-dt.timedelta(days=9)).isoformat()
        def row(day,value,status=None):
            result={"date":day,"value":value,
                    "lag_days":(now.date()-dt.date.fromisoformat(day)).days}
            if status is not None:result["status"]=status
            return result
        recent_mvrv=row(recent,1.5,"fresh") if core_available else {"date":None,"value":None,"lag_days":None,"status":"missing"}
        components={
          "latest.json":{"generated_utc":now.isoformat(),"latest":{
            "mvrv":recent_mvrv,
            "realized_price":row(old,54000,"delayed"),
            "sth_realized_price":row(old,78000,"delayed"),
            "lth_realized_price":row(old,49000,"delayed"),
          },"errors":[]},
          "bitview_latest.json":{"generated_utc":now.isoformat(),"latest":{
            "realized_price_bitview":row(recent,54100),
            "sth_realized_price_150d":row(recent,76000),
            "lth_realized_price_150d":row(recent,48900)
          },"errors":[]},
          "whale_latest.json":{"generated_utc":now.isoformat(),"latest":{
            "whale_exchange_deposit_count":row(recent,700),
            "whale_exchange_deposit_volume_btc":row(old,2500),
          },"errors":[]},
          "whale_alert_latest.json":{"generated_utc":now.isoformat(),
            "last_observed_day":recent,"first_observed_day":"2022-11-01",
            "observed_days":1000,
            "last_observed_day_data":{"observed_alert_count":4},
            "errors":[]},
          "whale_history.json":{"whale_exchange_deposit_count":{
             recent:700},"whale_exchange_deposit_volume_btc":{old:2500}},
        }
        # Simulate yesterday's stale cached lag_days next to genuinely old
        # source observation dates: consolidation must recompute each age.
        components["whale_latest.json"]["latest"]["whale_exchange_deposit_volume_btc"]["lag_days"]=1
        components["latest.json"]["latest"]["realized_price"]["lag_days"]=2
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            for filename,blob in components.items():
                (directory/filename).write_text(json.dumps(blob),encoding="utf-8")
            with mock.patch.object(c,"ROOT",directory):
                c.main()
            return json.loads((directory/"monitor_latest.json").read_text())

    def test_four_optional_old_sources_remain_dated_but_not_critical(self):
        data=self.build()
        optional=data["reference_only_delayed"]
        self.assertEqual(len(optional),4)
        self.assertEqual(len({(v["group"],v["metric"]) for v in optional}),4)
        self.assertTrue(all(v["lag_days"]>=9 for v in optional))
        self.assertEqual(data["components"]["whale_deposits"]["latest"]["whale_exchange_deposit_volume_btc"]["lag_days"],9)
        self.assertTrue(all(v["signal_eligible"] is False for v in optional))
        self.assertFalse(any("realized_price" in x for x in data["stale"]))
        self.assertFalse(any("whale_exchange_deposit_volume" in x for x in data["stale"]))
        self.assertEqual(data["components"]["market_onchain"]["latest"]["realized_price"]["value"],54000)
        self.assertEqual(data["components"]["lth_sth_bitview"]["latest"]["realized_price_bitview"]["value"],54100)

    def test_network_valuation_estimates_require_matched_closed_dates(self):
        today=dt.date(2026,11,6)
        days=[today-dt.timedelta(days=i) for i in range(1,201)]
        basis={d.isoformat():50000.0 for d in days}
        prices={"daily_closed":[{"day":d.isoformat(),"close":75000.0}
                                 for d in days]}
        data=c.derive_bitview_network_valuation(
            {"realized_price_bitview":basis},prices,today)
        self.assertEqual(data["mvrv_utxo_cost_basis_estimate"]["value"],1.5)
        self.assertAlmostEqual(data["nupl_utxo_cost_basis_estimate"]["value"],1/3,places=5)
        self.assertEqual(data["mvrv_utxo_cost_basis_estimate"]["date"],"2026-11-05")
        self.assertTrue(data["mvrv_utxo_cost_basis_estimate"]["not_bgeometrics_vendor_series"])
        self.assertEqual(c.derive_bitview_network_valuation(
            {"realized_price_bitview":basis},{"daily_closed":[]},today),{})

    def test_network_estimate_rejects_source_too_old(self):
        today=dt.date(2026,11,6)
        days=[today-dt.timedelta(days=i) for i in range(9,200)]
        basis={d.isoformat():50000.0 for d in days}
        prices={"daily_closed":[{"day":d.isoformat(),"close":75000.0}
                                 for d in days]}
        self.assertEqual(c.derive_bitview_network_valuation(
            {"realized_price_bitview":basis},prices,today),{})

    def test_missing_required_onchain_metric_still_surfaces(self):
        data=self.build(core_available=False)
        self.assertIn("market_onchain:mvrv",data["missing"])
        self.assertEqual(len(data["reference_only_delayed"]),4)

if __name__=="__main__":unittest.main()
