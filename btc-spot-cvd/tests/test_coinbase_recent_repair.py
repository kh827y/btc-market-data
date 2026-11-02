"""Recent Coinbase fixed-five CVD maintenance must not silently lose hours."""
import datetime as dt
from unittest import mock
import unittest
from coinbase_recent_repair import missing_groups,scan_group,repair
from coinbase_parallel_backfill import hour_key,UTC

NOW=dt.datetime(2026,11,2,19,40,tzinfo=UTC)
END=dt.datetime(2026,11,2,17,tzinfo=UTC)

class CoinbaseRecentRepairTests(unittest.TestCase):
    def test_recent_missing_hours_are_grouped_newest_first(self):
        current={hour_key(END-dt.timedelta(hours=i)):
                 {"complete":True,"net":10} for i in range(30)
                 if i not in (0,3,12,13)}
        state={"hourly":{"coinbase":current}}
        groups=missing_groups(state,END,horizon=30)
        self.assertEqual([len(g) for g in groups],[1,1,2])
        self.assertEqual([hour_key(g[0]) for g in groups],
                         ["2026-11-02T17:00:00Z",
                          "2026-11-02T14:00:00Z",
                          "2026-11-02T05:00:00Z"])

    def test_verified_repair_fills_gap_and_advances_window_without_reset(self):
        current={hour_key(END-dt.timedelta(hours=i)):
                 {"complete":True,"net":10} for i in range(30) if i!=0}
        state={"hourly":{"coinbase":current}}
        record={"complete":True,"source":"Coinbase Exchange REST",
                "net":1,"integrity":"id_continuous_verified","trades":100}
        with mock.patch("coinbase_recent_repair.scan_group",
              return_value=({"2026-11-02T17:00:00Z":record},2,None)) as scan:
            report=repair(state,NOW,[],pages=20,horizon=30)
        self.assertEqual(report["status"],"complete")
        self.assertEqual(report["hours_recovered"],1)
        self.assertEqual(report["hours_remaining"],0)
        self.assertEqual(scan.call_count,1)
        self.assertEqual(state["hourly"]["coinbase"]["2026-11-02T17:00:00Z"]["integrity"],
                         "id_continuous_verified")

    def test_page_cap_does_not_mark_partial_hour_complete(self):
        state={"hourly":{"coinbase":{}}}
        with mock.patch("coinbase_recent_repair.scan_group",
              return_value=(None,4,{"reason":"page_cap_reached_without_lower_boundary"})):
            report=repair(state,NOW,[],pages=4,horizon=1)
        self.assertEqual(report["status"],"partial")
        self.assertEqual(report["hours_remaining"],1)
        self.assertFalse(state["hourly"]["coinbase"])

    def test_no_missing_hours_does_not_fetch_api(self):
        current={hour_key(END-dt.timedelta(hours=i)):
                 {"complete":True} for i in range(30)}
        state={"hourly":{"coinbase":current}}
        with mock.patch("coinbase_recent_repair.scan_group") as scan:
            report=repair(state,NOW,[],pages=250,horizon=30)
        self.assertEqual(report["status"],"complete")
        self.assertEqual(report["pages_scanned"],0)
        scan.assert_not_called()

if __name__=="__main__":unittest.main()
