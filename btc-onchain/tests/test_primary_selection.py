"""On-chain free-tier cadence: do not waste quotas on source-gated recency."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
p=Path(__file__).resolve().parents[1]/"collector.py"
spec=importlib.util.spec_from_file_location("primary_onchain",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class PrimarySelectionTests(unittest.TestCase):
    def test_four_current_eligible_metrics_polled_daily(self):
        for offset in range(7):
            day=dt.date(2026,11,2)+dt.timedelta(days=offset)
            chosen=m.selected_metrics({},day)
            self.assertEqual(chosen[:4],list(m.CORE_NAMES))
            self.assertEqual(len(set(chosen)),len(chosen))
            self.assertLessEqual(len(chosen),6)

    def test_five_paid_recency_metrics_only_weekly_archive_checks(self):
        monday=dt.date(2026,11,2)
        for offset in range(7):
            day=monday+dt.timedelta(days=offset)
            restricted=[n for n in m.selected_metrics({},day) if n in m.RESTRICTED_WEEKDAY.values()]
            expected=[m.RESTRICTED_WEEKDAY[day.weekday()]] if day.weekday()<=4 else []
            self.assertEqual(restricted,expected)

    def test_original_cost_basis_prices_polled_once_each_week(self):
        expected={0:"sth_realized_price",2:"lth_realized_price",4:"realized_price"}
        for offset in range(7):
            day=dt.date(2026,11,2)+dt.timedelta(days=offset)
            chosen=m.selected_metrics({},day)
            optional=[x for x in chosen if x in expected.values()]
            self.assertEqual(optional,[expected[day.weekday()]] if day.weekday() in expected else [])

    def test_same_day_retries_do_not_requery_optional_or_paid_recency(self):
        day=dt.date(2026,11,4)
        prev={"optional_checked_utc_day":day.isoformat(),
              "optional_requested":"lth_realized_price",
              "restricted_checked_utc_day":day.isoformat(),
              "restricted_requested":"nupl"}
        self.assertEqual(m.selected_metrics({},day,prev),list(m.CORE_NAMES))
        self.assertIn("nupl",m.selected_metrics({},day+dt.timedelta(days=7),prev))
        self.assertIn("lth_realized_price",m.selected_metrics({},day+dt.timedelta(days=7),prev))

if __name__=="__main__":
    unittest.main()
