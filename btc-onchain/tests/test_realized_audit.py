import datetime as dt
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/"realized_audit.py"
spec=importlib.util.spec_from_file_location("realized_audit",path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class RealizedAuditTests(unittest.TestCase):
 def test_independent_lth_150d_is_available_but_not_equated_to_missing_original(self):
  now=dt.datetime(2026,11,2,9,tzinfo=m.UTC)
  primary={"realized_price":{"2026-10-26":54035.57},
           "sth_realized_price":{"2026-10-26":75834.46}}
  independent={"realized_price_bitview":{"2026-10-26":54059.38,"2026-11-01":54005.6},
     "sth_realized_price_150d":{"2026-10-26":75735.34,"2026-11-01":75817.9},
     "lth_realized_price_150d":{"2026-11-01":49003.22}}
  out=m.quality(primary,independent,now)
  self.assertEqual(out["lth_cost_basis_150d"]["alternate"]["value"],49003.22)
  self.assertFalse(out["lth_cost_basis_150d"]["identical_cohort_definition"])
  self.assertIsNone(out["lth_cost_basis_150d"]["primary"]["latest_date"])
  self.assertEqual(out["network_realized_price"]["cross_source_same_day"]["latest_compared_day"],"2026-10-26")
  self.assertLess(out["network_realized_price"]["cross_source_same_day"]["latest_absolute_difference_pct"],1)
  self.assertLess(out["sth_cost_basis_150d"]["cross_source_same_day"]["latest_absolute_difference_pct"],1)
 def test_old_and_future_bitview_do_not_count_as_current(self):
  now=dt.datetime(2026,11,2,9,tzinfo=m.UTC)
  old={"realized_price_bitview":{"2026-10-15":54000.0},
       "sth_realized_price_150d":{"2026-10-15":70000.0},
       "lth_realized_price_150d":{"2026-10-15":45000.0}}
  out=m.quality({},old,now)
  self.assertTrue(all(v["alternate"]["status"]=="missing_or_delayed" for v in out.values()))
  self.assertTrue(all(v["alternate"]["value"] is None for v in out.values()))
  future={"realized_price_bitview":{"2026-11-03":55000.0}}
  again=m.quality({},future,now)
  self.assertIsNone(again["network_realized_price"]["alternate"]["value"])
 def test_cross_source_comparisons_require_same_day_and_are_not_fabricated(self):
  now=dt.datetime(2026,11,2,9,tzinfo=m.UTC)
  j=m.quality({"realized_price":{"2026-10-25":54035.57}},
         {"realized_price_bitview":{"2026-10-26":54059.38}},now)
  self.assertEqual(j["network_realized_price"]["cross_source_same_day"]["n"],0)

if __name__=="__main__":unittest.main()
