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
        self.assertTrue(all(v["signal_eligible"] is False for v in optional))
        self.assertFalse(any("realized_price" in x for x in data["stale"]))
        self.assertFalse(any("whale_exchange_deposit_volume" in x for x in data["stale"]))
        self.assertEqual(data["components"]["market_onchain"]["latest"]["realized_price"]["value"],54000)
        self.assertEqual(data["components"]["lth_sth_bitview"]["latest"]["realized_price_bitview"]["value"],54100)

    def test_missing_required_onchain_metric_still_surfaces(self):
        data=self.build(core_available=False)
        self.assertIn("market_onchain:mvrv",data["missing"])
        self.assertEqual(len(data["reference_only_delayed"]),4)

if __name__=="__main__":unittest.main()
