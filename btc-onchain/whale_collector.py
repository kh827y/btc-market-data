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

def extract_swiss_week(markup):
    """Read published UTC day/ratio/count rows; no inference or fake backfill."""
    values = {}
    for item in re.findall(r"<tr[^>]*>.*?</tr>", markup, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", item, re.S | re.I)
        if len(cells) != 3:
            continue
        clean = [re.sub(r"<[^>]*>", "", cell).strip() for cell in cells]
        day, ratio, count = clean
        try:
            date = dt.date.fromisoformat(day)
            val = float(ratio)
            n = int(count.replace(",", ""))
            if not 0 <= val <= 1 or n < 0:
                continue
            values[date.isoformat()] = (val, n)
        except (ValueError, TypeError):
            continue
    if len(values) < 5:
        raise ValueError("fewer than five validated dated whale rows")
    return values

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
    try:
        dashboard = download("https://swisswhaleintelligence.com/dashboard/btc")
        seven_days = extract_swiss_week(dashboard)
        for day, (value, count) in seven_days.items():
            history.setdefault("whale_only_top10_deposit_ratio", {})[day] = value
            history.setdefault("swiss_whale_deposit_count_ge50", {})[day] = count
        most_recent = max(seven_days)
        latest["swiss_whale_deposit_count_ge50"] = {
            "date": most_recent,
            "value": seven_days[most_recent][1],
            "lag_days": (now.date() - dt.date.fromisoformat(most_recent)).days,
        }
        sources["swiss_whale_deposit_count_ge50"] = "Swiss Whale Intelligence; >=50 BTC tagged exchange deposits; NOT CoinGlass entity-labelled deposit count"
        if latest.get("whale_only_top10_deposit_ratio", {}).get("date") == most_recent:
            if abs(latest["whale_only_top10_deposit_ratio"]["value"] - seven_days[most_recent][0]) > 0.001:
                raise ValueError("Swiss dashboard / glossary disagreement")
    except Exception as exc:
        errors.append({"metric": "swiss_whale_deposit_count_ge50", "reason": str(exc)[:180]})
    result = {
        "generated_utc":now.isoformat(),
        "complete_for_latest":not errors and len(latest)==4,
        "history_is_complete":False,
        "history_note":"Only daily observations collected since first run; no fabricated historical points",
        "latest":latest,"source":sources,"errors":errors,
    }
    previous.write_text(json.dumps(history, separators=(",",":"),sort_keys=True)+"\n")
    (ROOT/"whale_latest.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
if __name__=="__main__":
    main()
