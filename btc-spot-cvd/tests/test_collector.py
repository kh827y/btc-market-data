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
if __name__=="__main__":unittest.main()
