"""Offline contracts for public keyless derivatives feeds.

Mocks are deliberately provider-shaped, so breaking schema, venue mapping and
single-sided timestamp assumptions fail CI before GitHub publishes data.
"""
import datetime as dt
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("btc_derivatives_collector", ROOT/"collector.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
UTC=dt.timezone.utc

class DerivativesFeedTests(TestCase):
    def test_oi_requires_five_fresh_named_venues(self):
        now=dt.datetime(2026,11,15,2,0,tzinfo=UTC)
        t=int(dt.datetime(2026,11,15,1,0,tzinfo=UTC).timestamp()*1000)
        keys={"Binance":"binance","Bybit":"bybit","OKX":"okx","Gate.io":"gate","Hyperliquid":"hyperliquid"}
        rows=[{"exchange":slug,"oi_usd":(i+1)*1e9,"updated_at":int(now.timestamp()*1000),
               "is_stale":False,"oi_side":"single"}
              for i,slug in enumerate(keys.values())]
        entries=[{"ts":t,"byExchange":{slug:(i+1)*1e9
                                     for i,slug in enumerate(keys.values())}}]
        def provider(path):
            return {"by_exchange":rows} if path.startswith("/sd/oi?") else {"data":entries}
        with mock.patch.object(module,"coinboss",side_effect=provider):
            result=module.fetch_oi(now)
        self.assertEqual(result["venues"],list(keys))
        self.assertEqual(result["latest_five_venue_usd"],15e9)
        self.assertEqual(result["latest_hour"],"2026-11-15T01:00:00Z")
        self.assertEqual(result["unit"],"USD notional (vendor normalized)")
        rows.pop()
        with mock.patch.object(module,"coinboss",side_effect=provider):
            with self.assertRaises(ValueError):
                module.fetch_oi(now)

    def test_liquidations_sum_only_two_verified_venues(self):
        now=dt.datetime(2026,11,15,2,0,tzinfo=UTC)
        sample={"now":int(now.timestamp()*1000),
            "sources":[{"exchange":"binance","status":"FRESH"},
                       {"exchange":"bybit","status":"FRESH"},
                       {"exchange":"other","status":"FRESH"}],
            "by_exchange":{"24h":[
                {"exchange":"binance","long_usd":120,"short_usd":30},
                {"exchange":"bybit","long_usd":90,"short_usd":20},
                {"exchange":"other","long_usd":99999,"short_usd":1000}]}}
        with mock.patch.object(module,"coinboss",return_value=sample):
            result=module.fetch_liquidations(now)["24h"]
        self.assertEqual(result["long_usd"],210)
        self.assertEqual(result["short_usd"],50)
        self.assertEqual(set(result["venues"]),{"binance","bybit"})
        sample["sources"][1]["status"]="STALE"
        with mock.patch.object(module,"coinboss",return_value=sample):
            with self.assertRaises(ValueError):
                module.fetch_liquidations(now)

    def test_settled_funding_is_not_predicted_rate(self):
        now=dt.datetime(2026,11,15,2,0,tzinfo=UTC)
        t=int(dt.datetime(2026,11,15,0,0,tzinfo=UTC).timestamp()*1000)
        live={"unit":"fraction","by_exchange":[]}
        history={"series":[]}
        cases=[("binance","BTCUSDT"),("bybit","BTCUSDT"),("okx","BTC-USDT-SWAP")]
        for venue,symbol in cases:
            live["by_exchange"].append({"exchange":venue,"primary":True,
                "symbol":symbol,"settled":{"last_time":t,"interval_h":8,
                "last_rate":0.0001},"predicted_rate":0.05})
            history["series"].append({"exchange":venue,"symbol":symbol,"complete":True,
                "points":[[t-8*3600000,0.3],[t,0.35]]})
        def provider(path):
            return live if path.startswith("/sd/funding?") else history
        with mock.patch.object(module,"coinboss",side_effect=provider):
            result=module.fetch_funding(now)
        self.assertEqual(set(result),{"Binance","Bybit","OKX"})
        self.assertAlmostEqual(result["Binance"]["latest_rate_8h"],0.0001)
        self.assertEqual(result["OKX"]["symbol"],"BTC-USDT-SWAP")
        self.assertEqual(result["OKX"]["count"],2)

