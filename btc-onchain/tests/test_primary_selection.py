import datetime as dt
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"collector.py"
spec=importlib.util.spec_from_file_location("primary_onchain",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class PrimarySelectionTests(unittest.TestCase):
 def test_missing_lth_price_is_seeded_without_exceeding_free_api_quota(self):
  date=dt.date(2026,11,2)
  selected=m.selected_metrics({},date)
  self.assertEqual(len(selected),11)
  self.assertEqual(selected.count("lth_realized_price"),1)
  self.assertIn("realized_price",selected)
 def test_existing_lth_price_returns_to_only_one_optional_per_day(self):
  date=dt.date(2026,11,2)
  selected=m.selected_metrics({"lth_realized_price":{"2026-10-26":49000}},date)
  self.assertEqual(len(selected),10)
  self.assertNotIn("lth_realized_price",selected)
 def test_rotation_lth_does_not_duplicate_request(self):
  date=dt.date(2026,11,1)
  selected=m.selected_metrics({},date)
  self.assertEqual(len(selected),10)
  self.assertEqual(selected.count("lth_realized_price"),1)

if __name__=="__main__":unittest.main()
