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
            "current":1793600000.125,
            "bids":[{"p":"77000","s":"100"},{"p":"76999","s":"200"}],
            "asks":[{"p":"77001","s":"150"},{"p":"77002","s":"200"}]})
        self.assertEqual(t,1793600000125)
        self.assertEqual(bids[0],["77000","100"])
        self.assertEqual(asks[0],["77001","150"])
    def test_restricted_source_403_not_retried(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        e=HTTPError("https://example.com",403,"Forbidden",None,None)
        with patch.object(m.urllib.request,"urlopen",side_effect=e) as f:
            with self.assertRaises(RuntimeError):
                m.fetch("https://example.com/api")
            self.assertEqual(f.call_count,1)

if __name__ == "__main__":
    unittest.main()
