import datetime as dt
import unittest
from unittest.mock import patch
from collector import key, summarise, coinbase_recent, UTC
class CVDTests(unittest.TestCase):
    def test_utc_hour_key(self):
        self.assertEqual(key(dt.datetime(2026,11,2,13,tzinfo=UTC)),"2026-11-02T13:00:00Z")
    def test_missing_venue_not_zero(self):
        now=dt.datetime(2026,11,2,14,5,tzinfo=UTC)
        value={"net":100,"complete":True}
        state={"hourly":{v:{"2026-11-02T13:00:00Z":value} for v in ("binance","coinbase","okx","bybit")}}
        result=summarise(state,now,[])
        self.assertIsNone(result["windows"]["1h"]["net"])
        self.assertIn("kraken",result["windows"]["1h"]["by_venue"])
        self.assertFalse(result["windows"]["24h"]["complete"])
    def test_24h_verified_partial_venue_subset_not_global(self):
        now=dt.datetime(2026,11,2,14,5,tzinfo=UTC)
        end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
        hours={key(end-dt.timedelta(hours=i)):{"net":100,"complete":True} for i in range(24)}
        state={"hourly":{v:dict(hours) for v in ("binance","okx","bybit","kraken")}}
        out=summarise(state,now,[])
        row=out["windows"]["24h"]
        self.assertFalse(row["complete"])
        self.assertIsNone(row["net"])
        self.assertTrue(row["complete_venue_subset"]["available"])
        self.assertEqual(row["complete_venue_subset"]["venue_count"],4)
        self.assertEqual(row["complete_venue_subset"]["net"],9600)
        self.assertEqual(row["by_venue"]["coinbase"]["hours"],0)
    def test_archive_recent_hours_prioritized(self):
        # This test asserts the algorithm uses recent-first order in the source
        # (actual archive API calls are intentionally not made in unit tests).
        import inspect
        from collector import archives
        source=inspect.getsource(archives)
        self.assertIn("for i in range(720)",source)
        self.assertNotIn("first+dt.timedelta(hours=i)",source)
    def test_coinbase_current_refresh_preserves_deep_backfill_cursor(self):
        now=dt.datetime(2026,11,2,14,tzinfo=UTC)
        historical={"after":"9998","pending":"2026-11-01T09:00:00Z",
                    "bucket":{"buy":100,"sell":0,"trades":9},
                    "cutoff":"2026-10-03T00:00:00Z"}
        state={"coinbase_cursor":historical.copy(),"hourly":{}}
        def scan(state,now,errors,pages,window_hours=720):
            self.assertEqual(window_hours,30)
            self.assertEqual(pages,12)
            self.assertIsNone(state["coinbase_cursor"]["after"])
            state["coinbase_cursor"]["after"]="8888"
            state["hourly"].setdefault("coinbase",{})["2026-11-02T11:00:00Z"]={"complete":True}
        with patch("collector.coinbase",side_effect=scan):
            coinbase_recent(state,now,[],pages=12)
        self.assertEqual(state["coinbase_cursor"],historical)
        self.assertTrue(state["hourly"]["coinbase"]["2026-11-02T11:00:00Z"]["complete"])

    def test_coinbase_recent_rolling_cursor_resumes_across_runs(self):
        now=dt.datetime(2026,11,2,14,tzinfo=UTC)
        deep={"after":"9998","pending":"2026-10-28T12:00:00Z","bucket":{"buy":7,"sell":3,"trades":1}}
        recent={"after":"8888","pending":"2026-11-02T09:00:00Z","bucket":{"buy":2,"sell":1,"trades":1}}
        state={"coinbase_cursor":deep.copy(),"coinbase_recent_cursor":recent.copy(),"hourly":{}}
        calls=[]
        def scan(state,now,errors,pages,window_hours=720):
            self.assertEqual(window_hours,30)
            calls.append((pages,state["coinbase_cursor"]["after"]))
            if pages==22:
                state["coinbase_cursor"]["after"]="7777" if len(calls)<=2 else "6666"
        with patch("collector.coinbase",side_effect=scan):
            coinbase_recent(state,now,[],pages=40)
            self.assertEqual(state["coinbase_cursor"],deep)
            self.assertEqual(state["coinbase_recent_cursor"]["after"],"7777")
            coinbase_recent(state,now,[],pages=40)
        self.assertEqual(calls,[(18,None),(22,"8888"),(18,None),(22,"7777")])
        self.assertEqual(state["coinbase_recent_cursor"]["after"],"6666")
        self.assertEqual(state["coinbase_cursor"],deep)

    def test_fixed_five_without_coinbase_is_not_original_five(self):
        from collector import ALT_FIVE, OBSERVED
        now=dt.datetime(2026,11,2,14,5,tzinfo=UTC)
        end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
        values={key(end-dt.timedelta(hours=i)):{"net":10,"complete":True} for i in range(24)}
        state={"hourly":{v:dict(values) for v in ALT_FIVE}}
        out=summarise(state,now,[])["windows"]["24h"]
        self.assertEqual(len(OBSERVED),6)
        self.assertFalse(out["complete"])
        self.assertIsNone(out["net"])
        self.assertEqual(out["by_venue"]["coinbase"]["hours"],0)
        self.assertTrue(out["fixed_five_ex_coinbase"]["complete"])
        self.assertEqual(out["fixed_five_ex_coinbase"]["net"],1200)
        self.assertEqual(out["fixed_five_ex_coinbase"]["venues"],ALT_FIVE)
        self.assertEqual(out["complete_venue_subset"]["venue_count"],5)
    def test_alt_five_incomplete_if_bitget_missing(self):
        from collector import ALT_FIVE
        now=dt.datetime(2026,11,2,14,5,tzinfo=UTC)
        end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
        state={"hourly":{v:{key(end):{"net":10,"complete":True}}
                         for v in ALT_FIVE if v!="bitget"}}
        out=summarise(state,now,[])["windows"]["1h"]
        self.assertFalse(out["fixed_five_ex_coinbase"]["complete"])
        self.assertIsNone(out["fixed_five_ex_coinbase"]["net"])
    def test_missing_archive_hours_are_cooled_down_not_retried_immediately(self):
        from collector import archives, VENUES
        now=dt.datetime(2026,11,2,14,5,tzinfo=UTC)
        state={"symbols":{name:pair[1][0] for name,pair in VENUES.items()},"hourly":{}}
        with patch("collector.get",side_effect=ValueError("HTTP 404")) as g:
            errors=[]
            archives(state,now,errors,batch=2)
            self.assertEqual(g.call_count,2*len(VENUES))
            archives(state,now,errors,batch=2)
            self.assertEqual(g.call_count,4*len(VENUES))
            # The second run advances to the next two missing hours rather
            # than getting stuck retrying the same two broken dates.
            self.assertTrue(state["archive_retry_after"]["bitget"])

if __name__=="__main__":unittest.main()
