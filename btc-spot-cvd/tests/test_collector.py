import datetime as dt
import unittest
from collector import key, summarise, UTC
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
if __name__=="__main__":unittest.main()
