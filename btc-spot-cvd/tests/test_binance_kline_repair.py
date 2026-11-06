import datetime as dt
import pathlib
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from binance_kline_repair import validated_hour, repair

UTC=dt.timezone.utc

def bar(hour, buy="250", total="900", trades=5):
    start=int(hour.timestamp()*1000)
    return [[start,"1","2","1","2","7",start+3599999,total,trades,
             "2",buy,"0"]]

class BinanceOfficialRepairTests(unittest.TestCase):
    def test_one_closed_bar_recovers_exact_executed_side(self):
        hour=dt.datetime(2026,11,5,17,tzinfo=UTC)
        a=validated_hour(hour,bar(hour))
        self.assertEqual(a["buy"],250)
        self.assertEqual(a["sell"],650)
        self.assertEqual(a["net"],-400)
        self.assertEqual(a["hour_basis"],"exchange_trade_time")

    def test_reject_missing_wrong_or_partial_hour(self):
        hour=dt.datetime(2026,11,5,17,tzinfo=UTC)
        for response in ([],bar(hour) * 2,
                         bar(hour+dt.timedelta(hours=1)),
                         bar(hour,buy="901"),
                         bar(hour,total="0")):
            with self.assertRaises(ValueError):
                validated_hour(hour,response)

    def test_only_fill_missing_and_maintain_cooldown(self):
        now=dt.datetime(2026,11,6,1,5,tzinfo=UTC)
        end=now.replace(minute=0,second=0)-dt.timedelta(hours=2)
        key=end.strftime("%Y-%m-%dT%H:00:00Z")
        yesterday=end-dt.timedelta(hours=1)
        prev=yesterday.strftime("%Y-%m-%dT%H:00:00Z")
        state={"hourly":{"binance":{key:{"complete":True,"net":100}}},
               "archive_retry_after":{"binance":{prev:now.timestamp()+43200}}}
        req=Mock()
        req.return_value.json.return_value=bar(yesterday)
        result=repair(state,now,[],req,max_hours=1)
        self.assertEqual(result["recovered"],1)
        self.assertEqual(state["hourly"]["binance"][key]["net"],100)
        self.assertEqual(state["hourly"]["binance"][prev]["net"],-400)
        self.assertNotIn(prev,state["archive_retry_after"]["binance"])
        self.assertEqual(req.call_count,1)
        self.assertEqual(repair(state,now,[],req,max_hours=1)["recovered"],0)

    def test_failure_keeps_gap_unknown(self):
        now=dt.datetime(2026,11,6,1,tzinfo=UTC)
        state={"hourly":{}}
        req=Mock(side_effect=ConnectionError("unreachable"))
        result=repair(state,now,[],req,max_hours=1)
        self.assertEqual(result["recovered"],0)
        self.assertEqual(state["hourly"]["binance"],{})
        repair(state,now,[],req,max_hours=1)
        self.assertEqual(req.call_count,2)  # second run advances to next hour
if __name__=="__main__":
    unittest.main()
