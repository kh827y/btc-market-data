import datetime as dt
import pathlib
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kraken_trade_repair import parse_page, repair

UTC=dt.timezone.utc
class KrakenRecoveryTests(unittest.TestCase):
    def test_sides_and_cursor_parsed(self):
        cursor, trades=parse_page({"error":[],"result":{"XXBTZUSD":[
            ["100","2",100.0,"b","l","",1],
            ["102","3",101.0,"s","l","",2]],"last":"102000000000"}})
        self.assertEqual(cursor,"102000000000")
        self.assertEqual(trades,[(100.0,"b",200.0),(101.0,"s",306.0)])

    def test_hour_requires_start_and_end_witnesses(self):
        now=dt.datetime(2026,11,6,1,tzinfo=UTC)
        hour=dt.datetime(2026,11,5,23,tzinfo=UTC)
        ts=hour.timestamp()
        request=Mock()
        request.return_value.json.return_value={"error":[],"result":{
            "XXBTZUSD":[["100","1",ts-5,"b","l",""],
                        ["200","2",ts+5,"b","l",""],
                        ["210","3",ts+200,"s","l",""],
                        ["220","1",ts+3602,"b","l",""]],
            "last":str(int((ts+3602)*1000000000))}}
        state={"hourly":{}}
        result=repair(state,now,[],request,max_pages=1)
        record=state["hourly"]["kraken"][hour.strftime("%Y-%m-%dT%H:00:00Z")]
        self.assertEqual(result["hours_recovered"],1)
        self.assertEqual(record["buy"],400)
        self.assertEqual(record["sell"],630)
        self.assertEqual(record["net"],-230)
        self.assertTrue(record["complete"])

    def test_no_start_witness_cannot_publish_hour(self):
        now=dt.datetime(2026,11,6,1,tzinfo=UTC)
        ts=dt.datetime(2026,11,5,23,tzinfo=UTC).timestamp()
        request=Mock()
        request.return_value.json.return_value={"error":[],"result":{
            "XXBTZUSD":[["200","1",ts+5,"b","l",""],
                        ["200","1",ts+3601,"s","l",""]],
            "last":str(int((ts+3601)*1000000000))}}
        state={"hourly":{}}
        errors=[]
        result=repair(state,now,errors,request,max_pages=1)
        self.assertEqual(result["hours_recovered"],0)
        self.assertFalse(state["hourly"]["kraken"])
        self.assertEqual(len(errors),1)
if __name__=="__main__":
    unittest.main()
