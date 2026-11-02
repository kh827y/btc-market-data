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

def aggregate(alerts, today):
    days={}
    seen=set()
    raw_btc=0
    selected=0
    for item in alerts:
        if item.get("blockchain")!="bitcoin" or item.get("transaction_type")!="transfer":
            continue
        raw_btc+=1
        dst=normalized(item.get("to"))
        src=normalized(item.get("from"))
        if dst not in EXCHANGES or src in EXCHANGES or src==dst:
            continue
        try:
            ts=int(item["timestamp"])
            moment=dt.datetime.fromtimestamp(ts,dt.timezone.utc)
            if moment.date()>today or moment.year<2018:
                continue
            amount=btc_amount(item)
            if not 0<amount<21000000:
                continue
        except (ValueError,TypeError,KeyError,OverflowError):
            continue
        tx=(item.get("transaction") or {}).get("hash")
        unique=(str(tx) if tx else str(ts)+src, dst, round(amount,8))
        if unique in seen:
            continue
        seen.add(unique)
        selected+=1
        day=moment.date().isoformat()
        row=days.setdefault(day,{
            "observed_alert_count":0,
            "observed_btc_volume":0.0,
            "count_ge_100_btc":0,"volume_ge_100_btc":0.0,
            "count_ge_1000_btc":0,"volume_ge_1000_btc":0.0,
        })
        row["observed_alert_count"]+=1
        row["observed_btc_volume"]+=amount
        for size in LIMITS:
            if amount>=size:
                row["count_ge_"+str(size)+"_btc"]+=1
                row["volume_ge_"+str(size)+"_btc"]+=amount
    for row in days.values():
        for key in ("observed_btc_volume","volume_ge_100_btc","volume_ge_1000_btc"):
            row[key]=round(row[key],8)
    if selected<1000:
        raise ValueError("Too few selected labelled BTC transfers; source/schema changed")
    return days,raw_btc,selected
