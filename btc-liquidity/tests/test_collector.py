"""Offline tests: no API keys and no live network assumptions."""
import csv
import datetime as dt
import importlib.util
import io
from pathlib import Path
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("liquidity_collector", Path(__file__).resolve().parents[1] / "collector.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def book(reach=0.4):
    # 25 distinct levels on each side; ticks cover +/- reach%.
    bids = [[str(100 - reach * i / 24), "2"] for i in range(25)]
    asks = [[str(100.001 + reach * i / 24), "2"] for i in range(25)]
    return bids, asks

def archive(frozen=False):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "percentage", "depth", "notional"])
    for i in range(1500):
        mid = 70000 + i * 0.1
        for band in (-2.0, -1.0, -0.2, 0.2, 1.0, 2.0):
            amount = {0.2: 10, 1.0: 20, 2.0: 30}[abs(band)] + i / 3000
            vwap = mid * (1 + band / 200)
            if frozen and band == 0.2:
                amount, vwap = 10, 70010
            writer.writerow([f"{i}", str(band), str(amount), str(amount * vwap)])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("BTCUSDT-bookDepth-2026-09-02.csv", buf.getvalue())
    return out.getvalue()

class LiquidityTests(unittest.TestCase):
    def test_book_coverage_missing_not_zero(self):
        bids, asks = book()
        r = m.summarize_orderbook(bids, asks)
        self.assertIsNotNone(r["bands"]["0.2"]["imbalance_bid_share"])
        self.assertIsNone(r["bands"]["1.0"]["bid_usd"])
        self.assertIsNone(r["bands"]["1.0"]["ask_usd"])
        self.assertFalse(r["bands"]["1.0"]["bid_coverage_complete"])
    def test_crossed_book_rejected(self):
        bids, asks = book()
        asks[0][0] = "99"
        with self.assertRaises(ValueError):
            m.summarize_orderbook(bids, asks)
    def test_history_known_good(self):
        value = m.parse_archive(archive(), dt.date(2026, 9, 2))
        self.assertEqual(value["snapshots"], 1500)
        self.assertGreater(value["bands"]["1.0"]["median_ask_notional_usd"], 1e6)
    def test_frozen_ask_archive_quarantined(self):
        with self.assertRaises(ValueError):
            m.parse_archive(archive(frozen=True), dt.date(2026, 9, 3))
    def test_okx_contract_multiplier_from_instrument(self):
        data = {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "ctValCcy": "BTC",
                "settleCcy": "USDT", "ctVal": "0.01", "ctMult": "1"}]}
        self.assertAlmostEqual(m.okx_swap_contract_size(data), 0.01)
        data["data"][0]["ctValCcy"] = "USD"
        with self.assertRaises(ValueError):
            m.okx_swap_contract_size(data)
    def test_old_samples_do_not_break_new_band_comparisons(self):
        now = dt.datetime(2026, 11, 2, 6, 0, tzinfo=m.UTC)
        old = {"time": (now - dt.timedelta(days=1)).isoformat(), "venues": {
            "okx_spot": {"bands": {"0.2": {"bid_usd": None, "ask_usd": None, "imbalance_bid_share": None}}}}}
        fresh = {"time": now.isoformat(), "venues": {"okx_spot": {"bands": {
            "0.05": {"bid_usd": 100, "ask_usd": 100, "imbalance_bid_share": .5},
            "0.2": {"bid_usd": None, "ask_usd": None, "imbalance_bid_share": None},
            "1.0": {"bid_usd": None, "ask_usd": None, "imbalance_bid_share": None}}}}}
        self.assertEqual(m.compare_lookback([old, fresh], now)["1d"], {})
    def test_comparisons_require_matching_observation(self):
        now = dt.datetime(2026, 11, 2, 6, 0, tzinfo=m.UTC)
        s = {"time": now.isoformat(), "venues": {"coinbase_spot": {
            "bands": {"0.2": {"bid_usd": 10, "ask_usd": 10, "imbalance_bid_share": .5},
                      "1.0": {"bid_usd": None, "ask_usd": None, "imbalance_bid_share": None}}
        }}}
        self.assertEqual(m.compare_lookback([s], now)["1d"], {})
    def test_bitget_v3_orderbook_parses_timestamp_and_side(self):
        obj={"code":"00000","data":{"b":[["80000","2"],["79999","3"]],
          "a":[["80001","4"],["80002","5"]],"ts":"1793600000123"}}
        bids,asks,stamp=m.normalize_book("bitget_usdt_perp",obj)
        self.assertEqual(bids[0],["80000","2"])
        self.assertEqual(asks[0],["80001","4"])
        self.assertEqual(stamp,1793600000123)
    def test_gate_direct_contract_multiplier_not_raw_contracts(self):
        self.assertAlmostEqual(m.gate_btc_contract_size({
            "name":"BTC_USDT","type":"direct","quanto_multiplier":"0.0001"}),0.0001)
        with self.assertRaises(ValueError):
            m.gate_btc_contract_size({"name":"BTC_USDT","type":"inverse",
                                      "quanto_multiplier":"0.0001"})
    def test_gate_futures_orderbook_seconds_timestamp(self):
        bids,asks,t=m.normalize_book("gate_usdt_perp",{
            "id":120009001,
            "current":1793600000.125,
            "bids":[{"p":"77000","s":"100"},{"p":"76999","s":"200"}],
            "asks":[{"p":"77001","s":"150"},{"p":"77002","s":"200"}]})
        self.assertEqual(t,1793600000125)
        self.assertEqual(bids[0],["77000","100"])
        self.assertEqual(asks[0],["77001","150"])
        self.assertIn("limit=300",m.VENUES["gate_usdt_perp"][2])
        self.assertIn("with_id=true",m.VENUES["gate_usdt_perp"][2])
        with self.assertRaisesRegex(ValueError,"update ID"):
            m.normalize_book("gate_usdt_perp",{"current":1793600000.125,
                "bids":[{"p":"77000","s":"1"}],"asks":[{"p":"77001","s":"1"}]})
    def test_restricted_source_403_not_retried(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        e=HTTPError("https://example.com",403,"Forbidden",None,None)
        with patch.object(m.urllib.request,"urlopen",side_effect=e) as f:
            with self.assertRaises(RuntimeError):
                m.fetch("https://example.com/api")
            self.assertEqual(f.call_count,1)


    def test_gate_v2_400_invalid_payload_falls_back_to_verified_rest_300(self):
        from unittest.mock import patch
        import official_ws
        now=dt.datetime.now(m.UTC)
        bid=[{"p":str(77000-i),"s":"100"} for i in range(20)]
        ask=[{"p":str(77001+i),"s":"100"} for i in range(20)]
        rest={"id":123457,"current":now.timestamp(),"bids":bid,"asks":ask}
        bad_ws=dict(rest)
        bad_ws["bids"]=[{"p":"77000","s":"100"}]  # invalid initial full book
        spec={"name":"BTC_USDT","type":"direct","quanto_multiplier":"0.0001"}
        urls={"gate_usdt_perp":m.VENUES["gate_usdt_perp"]}
        errors=[]
        def fake_fetch(url):
            return spec if "/contracts/" in url else rest
        with patch.object(m,"VENUES",urls), patch.object(m,"fetch",side_effect=fake_fetch), patch.object(official_ws,"read_gate_v2_book",return_value=bad_ws):
            result=m.collect_live(now,errors)
        value=result["venues"]["gate_usdt_perp"]
        self.assertEqual(value["levels"]["bid"],20)
        self.assertEqual(value["native_depth_levels_requested"],300)
        self.assertEqual(value["exchange_update_id"],123457)
        self.assertTrue(any("gate_v2_400_unavailable" in x for x in errors))
        self.assertEqual(value["bands"]["1.0"]["bid_usd"],None)

    def test_gate_v2_400_valid_snapshot_preferred_over_rest(self):
        from unittest.mock import patch
        import official_ws
        now=dt.datetime.now(m.UTC)
        raw={"id":123458,"current":now.timestamp(),
             "bids":[{"p":str(77000-i*.2),"s":"100"} for i in range(400)],
             "asks":[{"p":str(77000.1+i*.2),"s":"100"} for i in range(400)],
             "_transport":"gate_official_ws_v2_full_snapshot",
             "_source_url":official_ws.GATE_V2_URL,
             "_snapshot_type":"native_full_400_snapshot"}
        spec={"name":"BTC_USDT","type":"direct","quanto_multiplier":"0.0001"}
        urls={"gate_usdt_perp":m.VENUES["gate_usdt_perp"]}
        errors=[]
        def fake_fetch(url):
            if "/contracts/" in url:return spec
            raise AssertionError("should not fetch REST 300 when WS 400 is valid")
        with patch.object(m,"VENUES",urls),patch.object(m,"fetch",side_effect=fake_fetch),patch.object(official_ws,"read_gate_v2_book",return_value=raw):
            result=m.collect_live(now,errors)
        value=result["venues"]["gate_usdt_perp"]
        self.assertEqual(value["levels"]["ask"],400)
        self.assertEqual(value["native_depth_levels_requested"],400)
        self.assertEqual(value["exchange_update_id"],123458)
        self.assertEqual(value["transport"],"gate_official_ws_v2_full_snapshot")
        self.assertEqual(errors,[])


    def test_okx_official_full_5000_verified_and_400_fallback(self):
        from unittest.mock import patch
        now=dt.datetime.now(m.UTC)
        ts=str(int(now.timestamp()*1000))
        def snap(n):
            return {"code":"0","data":[{"bids":[[str(77000-i*.2),"2","1"] for i in range(n)],
                 "asks":[[str(77000.1+i*.2),"3","1"] for i in range(n)],"ts":ts}]}
        self.assertIn("books-full",m.VENUES["okx_spot"][2])
        self.assertIn("sz=5000",m.VENUES["okx_usdt_perp"][2])
        only={"okx_spot":m.VENUES["okx_spot"]}
        with patch.object(m,"VENUES",only),patch.object(m,"fetch",return_value=snap(5000)):
            errs=[]
            full=m.collect_live(now,errs)
        self.assertFalse(errs)
        self.assertEqual(full["venues"]["okx_spot"]["levels"]["bid"],5000)
        self.assertTrue(full["venues"]["okx_spot"]["bands"]["1.0"]["bid_coverage_complete"])
        def fake(url):
            return snap(20) if "/books-full?" in url else snap(400)
        with patch.object(m,"VENUES",only),patch.object(m,"fetch",side_effect=fake):
            errs=[]
            fallback=m.collect_live(now,errs)
        self.assertEqual(fallback["venues"]["okx_spot"]["native_depth_levels_requested"],400)
        self.assertEqual(fallback["venues"]["okx_spot"]["source_url"],"https://www.okx.com/api/v5/market/books")
        self.assertTrue(any("truncated sides" in e for e in errs))


    def test_gate_spot_native_5000_source_timestamp_and_update_id(self):
        self.assertIn("limit=5000",m.VENUES["gate_spot"][2])
        self.assertIn("with_id=true",m.VENUES["gate_spot"][2])
        now=dt.datetime.now(m.UTC)
        def raw(n=5000):
            return {"id":40770001,"current":int(now.timestamp()*1000),
                    "bids":[[str(77000-i*.25),"2"] for i in range(n)],
                    "asks":[[str(77000.1+i*.25),"3"] for i in range(n)]}
        bids,asks,ts=m.normalize_book("gate_spot",raw())
        self.assertEqual(ts,int(now.timestamp()*1000))
        self.assertEqual(len(bids),5000)
        for key in ("id","current"):
            bad=raw()
            bad.pop(key)
            with self.assertRaises((KeyError,TypeError,ValueError)):
                m.normalize_book("gate_spot",bad)
        bad=raw()
        bad["current"]=int(now.timestamp())
        with self.assertRaisesRegex(ValueError,"milliseconds"):
            m.normalize_book("gate_spot",bad)

    def test_gate_spot_5000_verified_and_1000_fallback(self):
        from unittest.mock import patch
        now=dt.datetime.now(m.UTC)
        def book(n):
            return {"id":40819000,"current":int(now.timestamp()*1000),
                    "bids":[[str(77000-i*.2),"2"] for i in range(n)],
                    "asks":[[str(77000.1+i*.2),"3"] for i in range(n)]}
        only={"gate_spot":m.VENUES["gate_spot"]}
        with patch.object(m,"VENUES",only),patch.object(m,"fetch",return_value=book(5000)):
            errors=[]
            full=m.collect_live(now,errors)
        self.assertEqual(errors,[])
        self.assertEqual(full["venues"]["gate_spot"]["native_depth_levels_requested"],5000)
        self.assertEqual(full["venues"]["gate_spot"]["exchange_update_id"],40819000)
        self.assertEqual(full["venues"]["gate_spot"]["levels"]["bid"],5000)
        self.assertIsNotNone(full["venues"]["gate_spot"]["bands"]["1.0"]["imbalance_bid_share"])
        urls=[]
        def fetcher(url):
            urls.append(url)
            return book(30 if "limit=5000" in url else 1000)
        with patch.object(m,"VENUES",only),patch.object(m,"fetch",side_effect=fetcher):
            errors=[]
            smaller=m.collect_live(now,errors)
        self.assertEqual(smaller["venues"]["gate_spot"]["native_depth_levels_requested"],1000)
        self.assertEqual(smaller["venues"]["gate_spot"]["transport"],"gate_official_rest_1000_fallback")
        self.assertTrue(any("gate_spot_5000_unavailable" in e for e in errors))
        self.assertTrue(any("limit=1000" in u for u in urls))

if __name__ == "__main__":
    unittest.main()
