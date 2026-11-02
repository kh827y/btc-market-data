"""Coinbase parallel free BTC spot CVD time/ID boundary invariants."""
import datetime as dt
import importlib.util
import pathlib
import unittest
from unittest import mock

SPEC=importlib.util.spec_from_file_location("coinbase_parallel",
    pathlib.Path(__file__).resolve().parents[1]/"coinbase_parallel_backfill.py")
m=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
UTC=dt.timezone.utc

class CoinbaseParallelTests(unittest.TestCase):
    def test_slice_60_hours_bounds_cover_720_without_overlapping(self):
        anchor=dt.datetime(2026,11,2,18,tzinfo=UTC)
        allhours=[]
        for i in range(m.SLICES):
            upper=anchor+dt.timedelta(hours=1-i*m.SLICE_HOURS)
            lower=upper-dt.timedelta(hours=m.SLICE_HOURS)
            allhours += [m.hour_key(lower+dt.timedelta(hours=j)) for j in range(m.SLICE_HOURS)]
        self.assertEqual(len(allhours),720)
        self.assertEqual(len(set(allhours)),720)
        self.assertEqual(min(allhours),"2026-10-03T19:00:00Z")
        self.assertEqual(max(allhours),"2026-11-02T18:00:00Z")

    def test_seek_off_by_one_uses_last_id_before_upper_boundary(self):
        upper=dt.datetime(2026,11,2,18,tzinfo=UTC)
        # Synthetic source whose 30m midpoints straddle 18:00 at id=9005.
        def fetch(_, after=None, limit=1000):
            head=9010
            id=head if after is None else int(after)-1
            stamp=upper+dt.timedelta(minutes=30*(id-9005))
            return ([{"trade_id":id,"time":stamp.isoformat()}],
                    [id],[stamp],str(id))
        with mock.patch.object(m,"fetch",side_effect=fetch):
            trace={}
            cursor=m.seek(None,upper,trace)
        self.assertEqual(cursor,9005)
        self.assertEqual(trace["cursor"],9005)

    def test_maker_sell_is_taker_buy_and_real_trade_times_are_bucketed(self):
        lower=dt.datetime(2026,11,1,12,tzinfo=UTC)
        upper=lower+dt.timedelta(hours=1)
        times=[lower+dt.timedelta(minutes=50),lower+dt.timedelta(minutes=5),
               lower-dt.timedelta(minutes=2)]
        rows=[{"trade_id":9,"price":"100.0","size":"2","side":"sell"},
              {"trade_id":8,"price":"101.0","size":"3","side":"buy"},
              {"trade_id":7,"price":"100.0","size":"3","side":"sell"}]
        buckets={}
        crossed=m.accumulate(rows,times,lower,upper,buckets)
        self.assertTrue(crossed)
        k=m.hour_key(lower)
        self.assertEqual(buckets[k]["buy"],200)
        self.assertEqual(buckets[k]["sell"],303)
        self.assertEqual(buckets[k]["trades"],2)
        self.assertEqual(buckets[k]["newest_trade_id"],9)
        self.assertEqual(buckets[k]["oldest_trade_id"],8)

    def test_trade_exactly_at_upper_never_leaks_into_closed_window(self):
        lower=dt.datetime(2026,11,1,12,tzinfo=UTC)
        with self.assertRaisesRegex(ValueError,"upper boundary"):
            m.accumulate([{"trade_id":1,"price":"100","size":"1","side":"buy"}],
                         [lower+dt.timedelta(hours=1)],
                         lower,lower+dt.timedelta(hours=1),{})

    def test_duplicate_or_missing_trade_id_in_page_is_hard_failure(self):
        class FakeResponse:
            status_code=200
            headers={"CB-AFTER":"7"}
            def raise_for_status(self):pass
            def json(self):
                return [{"trade_id":9,"time":"2026-11-01T10:00:00Z"},
                        {"trade_id":7,"time":"2026-11-01T09:59:00Z"}]
        class FakeSession:
            def get(self,*a,**k):return FakeResponse()
        with self.assertRaisesRegex(ValueError,"IDs missing"):
            m.fetch(FakeSession(),after=10)

    def test_empty_trade_page_cannot_be_marked_complete(self):
        class FakeResponse:
            status_code=200
            headers={"CB-AFTER":"1"}
            def raise_for_status(self):pass
            def json(self):return []
        class FakeSession:
            def get(self,*a,**k):return FakeResponse()
        with self.assertRaisesRegex(ValueError,"empty/invalid"):
            m.fetch(FakeSession(),after=5)

if __name__=="__main__":unittest.main()
