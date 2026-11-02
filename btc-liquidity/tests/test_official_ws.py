"""Offline fail-closed tests for native verified BTC official WebSocket books."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

src=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("official_ws",src/"official_ws.py")
ws=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)
spec2=importlib.util.spec_from_file_location("liquidity_collector",src/"collector.py")
book=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(book)

def sides(n=1000):
    bid=[["77000.0" if i==0 else str(77000-i*0.1),"1"] for i in range(n)]
    ask=[[str(77000.1+i*0.1),"1"] for i in range(n)]
    return bid,ask

class FakeConnection:
    def __init__(self,frames):
        self.frames=list(frames);self.sent=[];self.closed=False
    def send(self,s):self.sent.append(json.loads(s))
    def recv(self):return json.dumps(self.frames.pop(0))
    def close(self):self.closed=True

def bybit_frame(market="bybit_spot",msgtype="snapshot",topic=None,ts=None):
    b,a=sides()
    return {"topic":topic or ws.BYBIT[market]["topic"],"type":msgtype,
            "ts":ts or int(dt.datetime.now(ws.UTC).timestamp()*1000),
            "data":{"s":"BTCUSDT","b":b,"a":a,"u":120,"seq":121}}

def binance_response(request_id,source_ms=None):
    b,a=sides()
    return {"id":request_id,"status":200,"result":{
       "lastUpdateId":19402,
       "E":source_ms or int(dt.datetime.now(ws.UTC).timestamp()*1000),
       "T":int(dt.datetime.now(ws.UTC).timestamp()*1000),
       "bids":b,"asks":a}}

class OfficialWSTests(unittest.TestCase):
    def test_bybit_spot_full_book_has_both_sides(self):
        frame=bybit_frame()
        fake=FakeConnection([{"op":"subscribe","success":True},frame])
        out=ws.read_official_book("bybit_spot",lambda *a,**kw:fake)
        self.assertEqual(len(out["result"]["b"]),1000)
        self.assertEqual(len(out["result"]["a"]),1000)
        self.assertEqual(out["_transport"],"bybit_official_ws_snapshot")
        self.assertEqual(fake.sent[0]["args"],["orderbook.1000.BTCUSDT"])
        self.assertTrue(fake.closed)
        b,a,t=book.normalize_book("bybit_spot",out)
        self.assertIsNotNone(book.summarize_orderbook(b,a)["bands"]["0.05"]["imbalance_bid_share"])
        self.assertGreater(t,0)

    def test_bybit_linear_perpetual_keeps_own_market(self):
        fake=FakeConnection([bybit_frame("bybit_usdt_perp")])
        out=ws.read_official_book("bybit_usdt_perp",lambda *a,**kw:fake)
        self.assertIn("linear",out["_source_url"])
        self.assertEqual(out["result"]["s"],"BTCUSDT")

    def test_bybit_delta_not_accepted_as_full_book(self):
        self.assertIsNone(ws.bybit_snapshot(bybit_frame(msgtype="delta"),"bybit_spot"))

    def test_wrong_bybit_topic_not_used(self):
        self.assertIsNone(ws.bybit_snapshot(bybit_frame(topic="orderbook.1000.ETHUSDT"),"bybit_spot"))

    def test_bybit_mismatched_symbol_rejected(self):
        msg=bybit_frame()
        msg["data"]["s"]="ETHUSDT"
        with self.assertRaisesRegex(ws.UnverifiedBook,"symbol"):
            ws.bybit_snapshot(msg,"bybit_spot")

    def test_bybit_bad_seq_rejected(self):
        msg=bybit_frame()
        msg["data"].pop("seq")
        with self.assertRaisesRegex(ws.UnverifiedBook,"sequence"):
            ws.bybit_snapshot(msg,"bybit_spot")

    def test_binance_exact_ws_request_and_full_depth(self):
        def fake_factory(*a,**kw):
            class DynamicConnection(FakeConnection):
                def recv(self):
                    if not self.frames:
                        return json.dumps(binance_response(self.sent[0]["id"]))
                    return super().recv()
            return DynamicConnection([])
        out=ws.read_official_book("binance_usdm_perp",fake_factory)
        self.assertEqual(out["_transport"],"binance_official_ws_api_depth")
        b,a,t=book.normalize_book("binance_usdm_perp",out)
        self.assertEqual(len(b),1000)
        self.assertGreater(t,0)
        self.assertEqual(book.summarize_orderbook(b,a)["bands"]["0.05"]["bid_coverage_complete"],True)

    def test_binance_missing_update_id_fails_closed(self):
        msg=binance_response("probe")
        msg["result"].pop("lastUpdateId")
        with self.assertRaisesRegex(ws.UnverifiedBook,"update ID"):
            ws.binance_depth_response(msg,"probe")

    def test_future_and_stale_source_timestamps_rejected(self):
        now=dt.datetime(2026,11,2,18,0,tzinfo=ws.UTC)
        with self.assertRaisesRegex(ws.UnverifiedBook,"stale"):
            ws.valid_source_ms(int((now-dt.timedelta(hours=1)).timestamp()*1000),now)
        with self.assertRaisesRegex(ws.UnverifiedBook,"future"):
            ws.valid_source_ms(int((now+dt.timedelta(minutes=1)).timestamp()*1000),now)

    def test_wrong_binance_request_id_ignored(self):
        self.assertIsNone(ws.binance_depth_response(binance_response("wrong"),"right"))

    def test_connection_closed_after_rejection(self):
        fake=FakeConnection([bybit_frame(msgtype="delta") for _ in range(ws.MAX_FRAMES)])
        with self.assertRaisesRegex(ws.UnverifiedBook,"no verified"):
            ws.read_official_book("bybit_spot",lambda *a,**kw:fake)
        self.assertTrue(fake.closed)


    def test_gate_v2_native_400_full_book_is_accepted(self):
        b,a=sides(400)
        ts=int(dt.datetime.now(ws.UTC).timestamp()*1000)
        full={"channel":"futures.obu","event":"update",
              "result":{"s":"ob.BTC_USDT.400","full":True,"u":201,
                        "t":ts,"b":b,"a":a},"time_ms":ts}
        fake=FakeConnection([{"channel":"futures.obu","event":"subscribe",
                             "result":{"status":"success"}},full])
        out=ws.read_gate_v2_book(lambda *args,**kw:fake)
        self.assertTrue(fake.closed)
        self.assertEqual(fake.sent[0]["payload"],["ob.BTC_USDT.400"])
        self.assertEqual(out["_transport"],"gate_official_ws_v2_full_snapshot")
        self.assertEqual(out["id"],201)
        bid,ask,stamp=book.normalize_book("gate_usdt_perp",out)
        self.assertEqual(len(bid),400)
        self.assertEqual(len(ask),400)
        self.assertEqual(stamp,ts)
        self.assertIsNotNone(book.summarize_orderbook(bid,ask)["bands"]["0.01"]["imbalance_bid_share"])

    def test_gate_v2_deltas_and_wrong_symbol_are_not_accepted(self):
        b,a=sides(400)
        ts=int(dt.datetime.now(ws.UTC).timestamp()*1000)
        msg={"channel":"futures.obu","event":"update",
             "result":{"s":"ob.BTC_USDT.400","u":201,"t":ts,"b":b,"a":a}}
        self.assertIsNone(ws.gate_v2_snapshot(msg))
        msg["result"]["full"]=True
        msg["result"]["s"]="ob.ETH_USDT.400"
        with self.assertRaisesRegex(ws.UnverifiedBook,"instrument"):
            ws.gate_v2_snapshot(msg)
        msg["result"]["s"]="ob.BTC_USDT.400"
        msg["result"]["u"]=0
        with self.assertRaisesRegex(ws.UnverifiedBook,"update ID"):
            ws.gate_v2_snapshot(msg)
        msg["result"]["u"]=201
        msg["result"]["t"]=ts-3600*1000
        with self.assertRaisesRegex(ws.UnverifiedBook,"stale"):
            ws.gate_v2_snapshot(msg)

    def test_gate_v2_subscription_error_is_not_silent(self):
        msg={"channel":"futures.obu","event":"subscribe",
             "result":{"status":"fail"},"error":{"code":2}}
        with self.assertRaisesRegex(ws.UnverifiedBook,"subscription"):
            ws.gate_v2_snapshot(msg)

if __name__=="__main__":unittest.main()
