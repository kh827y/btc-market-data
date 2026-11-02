import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location("btc_price",Path(__file__).resolve().parents[1]/"collector.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
UTC=dt.timezone.utc

def fixture():
    first=dt.datetime(2021,1,4,tzinfo=UTC)
    days=[]
    for i in range(231*7):
        t=first+dt.timedelta(days=i)
        p=40000+10*i+(i%17)*2
        days.append({"open_ms":int(t.timestamp()*1000),"open":p,"high":p+50,
                     "low":p-50,"close":p+3,"volume_btc":100+i%7,"quote_volume_usdt":1e7})
    weeks=[]
    for i in range(231):
        rows=days[i*7:(i+1)*7]
        weeks.append({"open_ms":rows[0]["open_ms"],"open":rows[0]["open"],
          "high":max(x["high"] for x in rows),"low":min(x["low"] for x in rows),
          "close":rows[-1]["close"],"volume_btc":sum(x["volume_btc"] for x in rows),
          "quote_volume_usdt":sum(x["quote_volume_usdt"] for x in rows)})
    now=first+dt.timedelta(days=231*7)
    incomplete={"open_ms":int(now.timestamp()*1000),"open":9999999,
       "high":9999999,"low":1,"close":9999999,
       "volume_btc":99999,"quote_volume_usdt":1e8}
    return days[-800:]+[incomplete.copy()],weeks+[incomplete.copy()],now

class TechnicalTests(unittest.TestCase):
 def test_binance_official_fallback_uses_only_spot_api_hosts(self):
    seen=[]
    def fake(url):
        seen.append(url)
        if url.startswith("https://data-api.binance.vision/"):
            raise RuntimeError("primary host unavailable")
        return {"price":"78000"}
    with mock.patch.object(m,"request_json",side_effect=fake):
        result=m.binance_request("/api/v3/ticker/price?symbol=BTCUSDT")
    self.assertEqual(result["price"],"78000")
    self.assertEqual(len(seen),2)
    self.assertTrue(seen[0].startswith("https://data-api.binance.vision/api/v3/"))
    self.assertTrue(seen[1].startswith("https://api.binance.com/api/v3/"))

 def test_all_technical_indicators_use_completed_candles(self):
    d,w,now=fixture()
    j=m.calculate(d,w,now)
    self.assertEqual(j["coverage"]["daily_complete"],800)
    self.assertEqual(j["coverage"]["weekly_complete"],231)
    self.assertEqual(j["cross_checks"]["same_venue_daily_weekly_weeks"],8)
    self.assertEqual(j["daily"]["ma"]["ma20"],m.sma([x["close"] for x in d[:-1]],20))
    self.assertEqual(j["weekly"]["ma200"],m.sma([x["close"] for x in w[:-1]],200))
    self.assertLess(j["daily"]["close_usdt"],100000)
    self.assertEqual(j["cross_checks"]["coinbase_daily"]["status"],"unavailable")
 def test_partial_day_week_cannot_change_technical_signal(self):
    d,w,now=fixture()
    x=m.calculate(d,w,now)
    d[-1]["close"]=123456789
    w[-1]["close"]=123456789
    y=m.calculate(d,w,now)
    for field in ("rsi14_wilder","ma","breakout20","swings"):
        self.assertEqual(x["daily"][field],y["daily"][field])
    self.assertEqual(x["weekly"]["ma200"],y["weekly"]["ma200"])
 def test_missing_day_is_an_error_not_zero(self):
    d,w,now=fixture()
    del d[-20]
    with self.assertRaisesRegex(ValueError,"missing/duplicate 1d"):
        m.calculate(d,w,now)
 def test_missing_week_is_an_error_not_zero(self):
    d,w,now=fixture()
    del w[-8]
    with self.assertRaisesRegex(ValueError,"missing/duplicate 1w"):
        m.calculate(d,w,now)
 def test_independent_coinbase_crosscheck(self):
    d,w,now=fixture()
    close=d[-2]["close"]
    self.assertEqual(m.calculate(d,w,now,coinbase=close*1.005)
                     ["cross_checks"]["coinbase_daily"]["status"],"verified")
    with self.assertRaisesRegex(ValueError,"Coinbase"):
        m.calculate(d,w,now,coinbase=close*1.04)
 def test_same_exchange_daily_vs_weekly_close_disagreement(self):
    d,w,now=fixture()
    w[-2]["close"]+=10
    with self.assertRaisesRegex(ValueError,"weekly and daily OHLC"):
        m.calculate(d,w,now)
 def test_stale_week_quarantined(self):
    d,w,now=fixture()
    with self.assertRaisesRegex(ValueError,"latest 1w complete candle stale"):
        m.calculate(d,w[:-2],now)
 def test_wilder_rsi_flat_up_down(self):
    self.assertEqual(m.rsi_wilder([100.0]*35),50)
    self.assertEqual(m.rsi_wilder(list(range(100,140))),100)
    self.assertEqual(m.rsi_wilder(list(range(140,100,-1))),0)
 def test_pivot_classification_only_confirmed(self):
    d,w,now=fixture()
    pivots=m.swings(d[:-1])
    self.assertEqual(pivots["confirmed_right_bars"],3)
    self.assertTrue(all(x["day"]<now.date().isoformat() for x in pivots["recent_highs"]))

if __name__=="__main__":unittest.main()
