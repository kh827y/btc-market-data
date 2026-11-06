"""Free onchain collector cadence and source-date regression tests."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"collector.py"
spec=importlib.util.spec_from_file_location("primary_onchain",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class PrimarySelectionTests(unittest.TestCase):
    def test_nine_core_metrics_polled_daily_after_october_free_tier_change(self):
        for offset in range(7):
            day=dt.date(2026,11,2)+dt.timedelta(days=offset)
            chosen=m.selected_metrics({},day)
            self.assertEqual(chosen[:9],list(m.CORE_NAMES))
            self.assertEqual(len(set(chosen)),len(chosen))
            self.assertLessEqual(len(chosen),10)
        self.assertTrue({"mvrv","mvrv_zscore","nupl","sth_sopr","lth_sopr"}
                        .issubset(set(m.CORE_NAMES)))

    def test_original_cost_basis_prices_polled_once_each_week(self):
        expected={0:"sth_realized_price",2:"lth_realized_price",4:"realized_price"}
        for offset in range(7):
            day=dt.date(2026,11,2)+dt.timedelta(days=offset)
            optional=m.selected_metrics({},day)[9:]
            self.assertEqual(optional,[expected[day.weekday()]] if day.weekday() in expected else [])

    def test_same_day_retry_does_not_requery_optional_price(self):
        day=dt.date(2026,11,4)
        prev={"optional_checked_utc_day":day.isoformat(),
              "optional_requested":"lth_realized_price"}
        self.assertEqual(m.selected_metrics({},day,prev),list(m.CORE_NAMES))
        self.assertEqual(m.selected_metrics({},day+dt.timedelta(days=7),prev)[-1],
                         "lth_realized_price")
if __name__=="__main__":
    unittest.main()
