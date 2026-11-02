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

def extract_swiss(markup):
    value = re.search(r'Latest complete day</th><td>([\d.]+)</td>', markup)
    date = re.search(r'Data as of</th><td>(20\d\d-\d\d-\d\d)</td>', markup)
    if not value or not date:
        raise ValueError("Swiss whale-only ratio unavailable")
    v = float(value.group(1))
    if not 0 <= v <= 1:
        raise ValueError("ratio outside range")
    dt.date.fromisoformat(date.group(1))
    return date.group(1), v

def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    previous = ROOT / "whale_history.json"
    history = json.loads(previous.read_text()) if previous.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)
    errors = []
    latest = {}
    sources = {name:"CoinGlass: entity-labelled large-holder deposits" for name in PAGES}
    for name, slug in PAGES.items():
        try:
            markup = download("https://www.coinglass.com/pro/onchain/" + slug)
            day, value = extract_coinglass(markup)
            history.setdefault(name, {})[day] = value
            latest[name] = {"date":day,"value":value,"lag_days":(now.date()-dt.date.fromisoformat(day)).days}
        except Exception as exc:
            errors.append({"metric":name,"reason":str(exc)[:180]})
    try:
        markup = download("https://swisswhaleintelligence.com/glossary/exchange_whale_ratio/")
        day, value = extract_swiss(markup)
        name = "whale_only_top10_deposit_ratio"
        history.setdefault(name, {})[day] = value
        latest[name] = {"date":day,"value":value,"lag_days":(now.date()-dt.date.fromisoformat(day)).days}
        sources[name] = "Swiss Whale Intelligence: top-10 deposits / whale-size inflow only, not total inflow"
    except Exception as exc:
        errors.append({"metric":"whale_only_top10_deposit_ratio","reason":str(exc)[:180]})
    result = {
        "generated_utc":now.isoformat(),
        "complete_for_latest":not errors and len(latest)==3,
        "history_is_complete":False,
        "history_note":"Only daily observations collected since first run; no fabricated historical points",
        "latest":latest,"source":sources,"errors":errors,
    }
    previous.write_text(json.dumps(history, separators=(",",":"),sort_keys=True)+"\n")
    (ROOT/"whale_latest.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
if __name__=="__main__":
    main()
