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

def main():
    now=dt.datetime.now(dt.timezone.utc)
    alerts=load_alerts()
    daily,btc_count,selected=aggregate(alerts,now.date())
    dates=sorted(daily)
    if not dates or dates[-1] < (now.date()-dt.timedelta(days=10)).isoformat():
        raise ValueError("Historical whale-alert source is unexpectedly stale")
    yearly={}
    for day,row in daily.items():
        year=day[:4]
        totals=yearly.setdefault(year,{"observed_alerts_to_exchanges":0,"btc":0})
        totals["observed_alerts_to_exchanges"]+=row["observed_alert_count"]
        totals["btc"]+=row["observed_btc_volume"]
    for year in yearly:
        yearly[year]["btc"]=round(yearly[year]["btc"],8)
    report={
        "generated_utc":now.isoformat(),
        "source":ARCHIVE,
        "source_attribution":"Whale Alert, freely downloadable historical SOCIAL alerts",
        "method":"BTC-only transfer alerts from non-exchange/unknown label to listed exchange; de-duplicated by tx hash + destination + BTC amount",
        "scope":"Non-exhaustive public alert subset. NOT entity-wide whale holdings classification. Exchange tags and alert thresholds can change over time.",
        "not_equivalent_to":"CoinGlass Whale Exchange Deposit Count/Volume; Glassnode >=1000 BTC-holding entities; CryptoKeyhole >=1000 BTC single-deposit flows",
        "data_complete_as_total_cryptocurrency_market":False,
        "fully_comparable_year_to_year":False,
        "zero_missing_days_are_undefined":True,
        "all_archive_alerts":len(alerts),
        "btc_transfer_alerts":btc_count,
        "labelled_to_exchange_alerts":selected,
        "observed_days":len(dates),
        "first_observed_day":dates[0],
        "last_observed_day":dates[-1],
        "annual_observed":yearly,
        "last_observed_day_data":daily[dates[-1]],
        "missing_day_note":"Only days with observed public alerts are included; missing dates must not be interpreted as zero true transfers.",
    }
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/"whale_alert_daily.json").write_text(json.dumps(daily,sort_keys=True,separators=(",",":"))+"\\n")
    (OUTPUT/"whale_alert_latest.json").write_text(json.dumps(report,indent=2)+"\\n")
    print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":
    main()
