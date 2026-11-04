"""Budget/regression checks for free on-chain collector source selection."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"collector.py"
spec=importlib.util.spec_from_file_location("primary_onchain",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class PrimarySelectionTests(unittest.TestCase):
    def test_nine_core_metrics_are_requested_daily(self):
        for day_offset in range(7):
            day=dt.date(2026,11,2)+dt.timedelta(days=day_offset)
            selected=m.selected_metrics({},day)
            self.assertEqual(selected[:9],list(m.CORE_NAMES))
            self.assertEqual(len(set(selected)),len(selected))
            self.assertLessEqual(len(selected),10)

    def test_original_prices_polled_once_each_per_week_not_daily(self):
        expected={0:"sth_realized_price",2:"lth_realized_price",
                  4:"realized_price"}
        for day_offset in range(7):
            day=dt.date(2026,11,2)+dt.timedelta(days=day_offset)
            actual=m.selected_metrics({},day)[9:]
            self.assertEqual(actual,[expected[day.weekday()]] if day.weekday() in expected else [])

    def test_empty_lth_history_does_not_consume_other_days_slots(self):
        monday=dt.date(2026,11,2)
        tuesday=monday+dt.timedelta(days=1)
        wednesday=monday+dt.timedelta(days=2)
        self.assertNotIn("lth_realized_price",m.selected_metrics({},monday))
        self.assertNotIn("lth_realized_price",m.selected_metrics({},tuesday))
        self.assertEqual(m.selected_metrics({},wednesday)[-1],"lth_realized_price")

    def test_same_day_redispatch_skips_optional_vendor_poll(self):
        day=dt.date(2026,11,4)
        previous={"optional_checked_utc_day":day.isoformat(),
                  "optional_requested":"lth_realized_price"}
        self.assertEqual(len(m.selected_metrics({},day,previous)),9)
        following=day+dt.timedelta(days=1)
        self.assertEqual(len(m.selected_metrics({},following,previous)),9)

    def test_next_week_same_metric_is_eligible_again(self):
        day=dt.date(2026,11,11)
        previous={"optional_checked_utc_day":"2026-11-04",
                  "optional_requested":"lth_realized_price"}
        self.assertEqual(m.selected_metrics({},day,previous)[-1],"lth_realized_price")

if __name__=="__main__":unittest.main()
