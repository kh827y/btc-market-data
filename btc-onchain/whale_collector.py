"""Public labeled-entity whale exchange deposit snapshots; no synthetic backfill."""
import datetime as dt
import json
import pathlib
import re
import urllib.request

PAGES = {
    "whale_exchange_deposit_volume_btc": "bitcoin-whale-exchange-deposit-volume",
    "whale_exchange_deposit_count": "bitcoin-whale-exchange-deposit-count",
}
ROOT = pathlib.Path("btc-onchain/data")
def download(url):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"})
    with urllib.request.urlopen(req, timeout=28) as resp:
        return resp.read(300000).decode("utf-8", errors="replace")

def extract_coinglass(markup):
    match = re.search(r'KpiStrip_label[^>]*>Latest</span>.*?KpiStrip_sub[^>]*>(20\d\d-\d\d-\d\d) · ([\d,.]+)', markup, re.S)
    if not match:
        raise ValueError("dated latest numeric KPI not present")
    day, raw = match.groups()
    date = dt.date.fromisoformat(day)
    value = float(raw.replace(",", ""))
    if value < 0:
        raise ValueError("invalid negative whale deposit")
    return day, value
