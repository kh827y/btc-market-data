"""Daily whale-to-exchange alerts from Whale Alert's free OFFICIAL archive.

This is an observed SOCIAL-ALERT SUBSET, not complete entity-clustered
CoinGlass/Glassnode onchain whale exchange deposit count or volume.
"""
import collections
import datetime as dt
import gzip
import json
from pathlib import Path
import urllib.request

ARCHIVE="https://whale-alert.io/whale-alerts-archive.json.gzip"
OUTPUT=Path("btc-onchain/data")
EXCHANGES={
    "binance","coinbase","coinbase institutional","kraken","bitstamp",
    "bitfinex","gemini","okex","okx","bybit","kucoin","huobi",
    "cryptocom","bitbank","bittrex","robinhood","poloniex","bitflyer",
    "bitget","gate","gate.io","mexc","upbit","bithumb","deribit",
    "bitmex","hitbtc","coinex","luno","bitso","bitvavo","korbit",
}
LIMITS=(100,1000)

def load_alerts():
    req=urllib.request.Request(ARCHIVE,headers={"User-Agent":"BTC-free-onchain-research/1.0"})
    with urllib.request.urlopen(req,timeout=90) as res:
        with gzip.GzipFile(fileobj=res) as stream:
            alerts=json.load(stream)
    if not isinstance(alerts,list) or len(alerts)<20000:
        raise ValueError("Official whale alert archive missing or too short")
    return alerts

def normalized(value):
    return str(value or "").strip().lower()

def btc_amount(alert):
    return sum(float(x.get("amount",0)) for x in alert.get("amounts",[])
               if str(x.get("symbol","")).upper()=="BTC")
