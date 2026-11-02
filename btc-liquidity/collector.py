"""BTC visible order-book liquidity. Free sources; spot != perpetual; unknown != zero."""
import csv
import datetime as dt
import io
import json
import math
import pathlib
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict

UTC = dt.timezone.utc
ROOT = pathlib.Path("btc-liquidity/data")
BANDS = (0.01, 0.05, 0.2, 1.0)  # shallow books require separately labeled inner 0.01% band
ARCHIVE_START = dt.date(2026, 6, 1)
ARCHIVE_LAST_SAFE = dt.date(2026, 9, 2)  # Binance exporter corruption since Sep 3, 2026
VENUES = {
    "binance_spot": ("spot", "BTCUSDT", "https://data-api.binance.vision/api/v3/depth?symbol=BTCUSDT&limit=5000"),
    "coinbase_spot": ("spot", "BTCUSD", "https://api.exchange.coinbase.com/products/BTC-USD/book?level=2"),
    "bybit_spot": ("spot", "BTCUSDT", "https://api.bybit.com/v5/market/orderbook?category=spot&symbol=BTCUSDT&limit=1000"),
    "okx_spot": ("spot", "BTCUSDT", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=400"),
    "binance_usdm_perp": ("perpetual", "BTCUSDT", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000"),
    "bybit_usdt_perp": ("perpetual", "BTCUSDT", "https://api.bybit.com/v5/market/orderbook?category=linear&symbol=BTCUSDT&limit=1000"),
    "okx_usdt_perp": ("perpetual", "BTCUSDT", "https://www.okx.com/api/v5/market/books?instId=BTC-USDT-SWAP&sz=400"),
    # Distinct real exchanges, NOT substitutes presented as Bybit/Binance.
    "bitget_spot": ("spot", "BTCUSDT", "https://api.bitget.com/api/v3/market/orderbook?category=SPOT&symbol=BTCUSDT&limit=1000"),
    "bitget_usdt_perp": ("perpetual", "BTCUSDT", "https://api.bitget.com/api/v3/market/orderbook?category=USDT-FUTURES&symbol=BTCUSDT&limit=1000"),
    "gate_spot": ("spot", "BTCUSDT", "https://api.gateio.ws/api/v4/spot/order_book?currency_pair=BTC_USDT&limit=1000"),
    "gate_usdt_perp": ("perpetual", "BTCUSDT", "https://api.gateio.ws/api/v4/futures/usdt/order_book?contract=BTC_USDT&limit=1000"),
}

def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "BTC-independent-market-research/1.0", "Accept": "application/json,application/zip,*/*"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read(10_000_001)
                if len(raw) > 10_000_000:
                    raise ValueError("oversized response")
                return raw if binary else json.loads(raw)
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400,401,403,404,451):
                # These are not transient. Do not retry a geo/auth denied host.
                break
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError("data fetch failed: " + str(last)[:160])

def finite_positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("nonpositive/nonfinite book value")
    return number

def normalize_book(venue, raw):
    if venue.startswith("bybit"):
        if raw.get("retCode") != 0:
            raise ValueError("Bybit nonzero retCode")
        item = raw["result"]
        bids, asks = item["b"], item["a"]
        source_ms = int(item["ts"])
    elif venue.startswith("bitget"):
        if raw.get("code") != "00000":
            raise ValueError("Bitget non-success response")
        item = raw["data"]
        bids, asks = item["b"], item["a"]
        source_ms = int(item["ts"])
    elif venue == "gate_spot":
        bids, asks = raw["bids"], raw["asks"]
        source_ms = None
    elif venue == "gate_usdt_perp":
        bids = [[item["p"], item["s"]] for item in raw["bids"]]
        asks = [[item["p"], item["s"]] for item in raw["asks"]]
        # Gate's current/update timestamps are expressed in SECONDS.
        source_ms = int(float(raw["current"]) * 1000)
    elif venue.startswith("okx"):
        if raw.get("code") != "0":
            raise ValueError("OKX nonzero code")
        item = raw["data"][0]
        bids, asks = item["bids"], item["asks"]
        source_ms = int(item["ts"])
    else:
        bids, asks = raw["bids"], raw["asks"]
        source_ms = None
    return bids, asks, source_ms

def parse_side(rows, descending):
    if not isinstance(rows, list) or len(rows) < 10:
        raise ValueError("insufficient book levels")
    out = [(finite_positive(x[0]), finite_positive(x[1])) for x in rows]
    for (p, _), (p2, _) in zip(out, out[1:]):
        if (descending and p <= p2) or (not descending and p >= p2):
            raise ValueError("book prices not strictly ordered")
    return out

def summarize_orderbook(bids_raw, asks_raw):
    bids = parse_side(bids_raw, True)
    asks = parse_side(asks_raw, False)
    best_bid, best_ask = bids[0][0], asks[0][0]
    if not 0 < best_bid < best_ask:
        raise ValueError("crossed/empty book")
    midpoint = (best_bid + best_ask) / 2
    spread_bps = (best_ask - best_bid) / midpoint * 10000
    if spread_bps > 40:
        raise ValueError("abnormal spread (>40bps)")
    result = {
        "mid_usd": round(midpoint, 3),
        "spread_bps": round(spread_bps, 3),
        "levels": {"bid": len(bids), "ask": len(asks)},
        "reach_pct": {"bid": round((midpoint - bids[-1][0]) / midpoint * 100, 4),
                      "ask": round((asks[-1][0] - midpoint) / midpoint * 100, 4)},
        "bands": {},
    }
    for band in BANDS:
        key = str(band)
        # A feed that stops inside the band is incomplete: unknown, never zero.
        bid_complete = bids[-1][0] <= midpoint * (1 - band / 100)
        ask_complete = asks[-1][0] >= midpoint * (1 + band / 100)
        bid_total = sum(p * qty for p, qty in bids if p >= midpoint * (1 - band / 100)) if bid_complete else None
        ask_total = sum(p * qty for p, qty in asks if p <= midpoint * (1 + band / 100)) if ask_complete else None
        result["bands"][key] = {
            "bid_usd": round(bid_total, 2) if bid_total is not None else None,
            "ask_usd": round(ask_total, 2) if ask_total is not None else None,
            "bid_coverage_complete": bid_complete, "ask_coverage_complete": ask_complete,
            "imbalance_bid_share": round(bid_total / (bid_total + ask_total), 5)
                if bid_total is not None and ask_total is not None and bid_total + ask_total > 0 else None,
        }
    return result

def okx_swap_contract_size(record):
    if record.get("code") != "0" or not record.get("data"):
        raise ValueError("OKX instrument metadata unavailable")
    item = record["data"][0]
    if (item.get("instId") != "BTC-USDT-SWAP" or item.get("ctValCcy") != "BTC"
            or item.get("settleCcy") != "USDT"):
        raise ValueError("OKX swap contract denomination changed; do not interpret contracts as BTC")
    return finite_positive(item["ctVal"]) * finite_positive(item["ctMult"])

def gate_btc_contract_size(record):
    # Gate USD-margined direct contract; book "s" is number of contracts,
    # not base BTC. Reject any change of type or missing multiplier.
    if not isinstance(record,dict) or record.get("name") != "BTC_USDT":
        raise ValueError("Gate contract metadata missing/wrong symbol")
    if record.get("type") not in ("direct","direct_contract"):
        raise ValueError("Gate futures contract type not verified as direct")
    return finite_positive(record["quanto_multiplier"])

def collect_live(now, errors):
    captured = now.isoformat().replace("+00:00", "Z")
    venues = {}
    for name, (market, symbol, url) in VENUES.items():
        try:
            raw = fetch(url)
            bids, asks, source_ms = normalize_book(name, raw)
            contract_size = None
            if name == "gate_usdt_perp":
                spec = fetch("https://api.gateio.ws/api/v4/futures/usdt/contracts/BTC_USDT")
                contract_size = gate_btc_contract_size(spec)
                bids = [[row[0], str(float(row[1]) * contract_size)] for row in bids]
                asks = [[row[0], str(float(row[1]) * contract_size)] for row in asks]
            if name == "okx_usdt_perp":
                spec = fetch("https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP")
                contract_size = okx_swap_contract_size(spec)
                # OKX orderbook size is number of contracts, not base BTC.
                bids = [[row[0], str(float(row[1]) * contract_size)] for row in bids]
                asks = [[row[0], str(float(row[1]) * contract_size)] for row in asks]
            if source_ms is not None and abs(dt.datetime.now(UTC).timestamp() * 1000 - source_ms) > 120_000:
                raise ValueError("stale source timestamp")
            record = summarize_orderbook(bids, asks)
            if contract_size is not None:
                record["contract_size_btc"] = contract_size
                record["quantity_conversion"] = ("Gate contracts times quanto_multiplier into BTC"
                                                if name == "gate_usdt_perp" else
                                                "OKX contracts times ctVal times ctMult into BTC")
            record.update({"market": market, "symbol": symbol, "quote": "USD" if name == "coinbase_spot" else "USDT",
                           "captured_at": dt.datetime.now(UTC).isoformat().replace("+00:00", "Z"), "source_timestamp": dt.datetime.fromtimestamp(source_ms / 1000, UTC).isoformat()
                           if source_ms is not None else None, "source_url": url.split("?")[0]})
            venues[name] = record
        except Exception as exc:
            errors.append(f"{name}: {str(exc)[:180]}")
    # Large divergence indicates a stale/inconsistent venue; don't derive multi-venue results.
    if len(venues) >= 2:
        prices = [v["mid_usd"] for v in venues.values()]
        mid = statistics.median(prices)
        for name in list(venues):
            if abs(venues[name]["mid_usd"] / mid - 1) > 0.03:
                errors.append(f"{name}: anomalous 3% deviation from cross-venue median")
                del venues[name]
    return {"time": captured, "venues": venues}

def daily_summary(samples):
    by_day = defaultdict(lambda: defaultdict(list))
    for sample in samples:
        for venue, item in sample.get("venues", {}).items():
            by_day[sample["time"][:10]][venue].append(item)
    out = {}
    for day, by_venue in sorted(by_day.items()):
        out[day] = {}
        for venue, rows in by_venue.items():
            bands = {}
            for band in BANDS:
                k = str(band)
                good = [x["bands"][k] for x in rows if x["bands"].get(k, {}).get("imbalance_bid_share") is not None]
                bands[k] = ({"samples": len(good),
                             "median_bid_usd": round(statistics.median(x["bid_usd"] for x in good), 2),
                             "median_ask_usd": round(statistics.median(x["ask_usd"] for x in good), 2),
                             "median_bid_share": round(statistics.median(x["imbalance_bid_share"] for x in good), 5)}
                            if len(good) >= 4 else None)
            out[day][venue] = {"market": rows[0]["market"], "samples": len(rows),
                               "bands": bands,
                               "median_spread_bps": round(statistics.median(x["spread_bps"] for x in rows), 3)}
    return out

def compare_lookback(samples, now):
    if not samples:
        return {}
    latest = samples[-1]
    result = {}
    for days in (1, 7, 30):
        goal = now - dt.timedelta(days=days)
        candidates = [s for s in samples[:-1] if abs((dt.datetime.fromisoformat(s["time"].replace("Z", "+00:00")) - goal).total_seconds()) <= 3 * 3600]
        base = min(candidates, key=lambda s: abs((dt.datetime.fromisoformat(s["time"].replace("Z", "+00:00")) - goal).total_seconds()), default=None)
        result[str(days) + "d"] = {}
        for name, current in latest["venues"].items():
            old = (base or {}).get("venues", {}).get(name)
            if not old:
                continue
            bands = {}
            for band in BANDS:
                k = str(band)
                a, b = current["bands"].get(k), old["bands"].get(k)
                if not a or not b or a["imbalance_bid_share"] is None or b["imbalance_bid_share"] is None:
                    continue
                bands[k] = {
                    "bid_depth_change_pct": round((a["bid_usd"] / b["bid_usd"] - 1) * 100, 2) if b["bid_usd"] else None,
                    "ask_depth_change_pct": round((a["ask_usd"] / b["ask_usd"] - 1) * 100, 2) if b["ask_usd"] else None,
                    "bid_share_change_pp": round((a["imbalance_bid_share"] - b["imbalance_bid_share"]) * 100, 3),
                }
            if bands:
                result[str(days) + "d"][name] = {"compared_to": base["time"], "bands": bands}
    return result

def parse_archive(data, day):
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        names = [n for n in zipped.namelist() if n.endswith(".csv") and ".." not in n]
        if len(names) != 1:
            raise ValueError("unexpected archive CSV files")
        with zipped.open(names[0]) as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
            if not {"timestamp", "percentage", "depth", "notional"}.issubset(reader.fieldnames or []):
                raise ValueError("unexpected Binance bookDepth columns")
            snapshots = defaultdict(dict)
            for row in reader:
                percentage = float(row["percentage"])
                if percentage not in (-2.0, -1.0, -0.2, 0.2, 1.0, 2.0):
                    continue
                depth, notional = finite_positive(row["depth"]), finite_positive(row["notional"])
                snapshots[row["timestamp"]][percentage] = (depth, notional)
    if len(snapshots) < 1400:
        raise ValueError("insufficient 30-second orderbook snapshots")
    valid = []
    for bands in snapshots.values():
        if all(k in bands for k in (-1., -0.2, 0.2, 1., -2., 2.)):
            # Same-side band depth should be monotonically cumulative; asks above bids.
            if not (bands[-2.][1] >= bands[-1.][1] >= bands[-0.2][1] > 0
                    and bands[2.][1] >= bands[1.][1] >= bands[0.2][1] > 0):
                continue
            if bands[0.2][1] / bands[0.2][0] <= bands[-0.2][1] / bands[-0.2][0]:
                continue
            valid.append(bands)
    if len(valid) < 0.9 * len(snapshots):
        raise ValueError("crossed/nonmonotone/frozen archive depth; reject day")
    for band in (-0.2, 0.2, -1., 1.):
        distinct = len({round(x[band][1] / x[band][0], 4) for x in valid})
        if distinct < max(100, len(valid) * 0.25):
            raise ValueError("stale/frozen depth band " + str(band))
    result = {"date": day.isoformat(), "market": "USD-M BTCUSDT perpetual (NOT spot)",
              "source": "https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/",
              "snapshots": len(valid), "bands": {}}
    for band in (0.2, 1.0, 2.0):
        b = statistics.median(x[-band][1] for x in valid)
        a = statistics.median(x[band][1] for x in valid)
        result["bands"][str(band)] = {"median_bid_notional_usd": round(b, 2),
                                      "median_ask_notional_usd": round(a, 2),
                                      "median_bid_share": round(b / (b + a), 5)}
    return result

def backfill_futures(history, checks, errors, max_days=100):
    # Do not fetch 2026-09-03 onward: known frozen ask bands in Binance public exporter.
    dates = [ARCHIVE_LAST_SAFE - dt.timedelta(days=d) for d in range((ARCHIVE_LAST_SAFE - ARCHIVE_START).days + 1)]
    attempts = 0
    start = time.monotonic()
    for day in dates:
        if time.monotonic() - start > 450:
            errors.append("archive backfill paused after 450s; resumes on next run")
            break
        key = day.isoformat()
        if key in history or checks.get(key, {}).get("permanent"):
            continue
        if attempts >= max_days:
            break
        attempts += 1
        url = f"https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-{key}.zip"
        try:
            history[key] = parse_archive(fetch(url, binary=True), day)
            checks.pop(key, None)
        except Exception as exc:
            prior = checks.get(key, {})
            count = prior.get("attempts", 0) + 1
            checks[key] = {"attempts": count, "error": str(exc)[:180], "permanent": count >= 3}
            errors.append(f"futures_archive {key}: {str(exc)[:140]}")
    return history

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default

def main():
    now = dt.datetime.now(UTC)
    errors = []
    previous = read(ROOT / "history.json", {"samples": [], "archived_futures_daily": {}, "archive_checks": {}})
    sample = collect_live(now, errors)
    old_samples = previous.get("samples", [])
    cutoff = now - dt.timedelta(days=32)
    samples = [s for s in old_samples if dt.datetime.fromisoformat(s["time"].replace("Z", "+00:00")) >= cutoff]
    if sample["venues"]:
        samples.append(sample)
    samples = sorted({s["time"]: s for s in samples}.values(), key=lambda s: s["time"])
    archive = previous.get("archived_futures_daily", {})
    checks = previous.get("archive_checks", {})
    backfill_futures(archive, checks, errors)
    history = {"schema_version": 1, "updated_at": now.isoformat(), "samples": samples,
               "archived_futures_daily": dict(sorted(archive.items())),
               "archive_checks": checks}
    write(ROOT / "history.json", history)
    spot_count = sum(v["market"] == "spot" for v in sample["venues"].values())
    perp_count = sum(v["market"] == "perpetual" for v in sample["venues"].values())
    spot_usable = sum(v["market"] == "spot" and any(b["imbalance_bid_share"] is not None for b in v["bands"].values()) for v in sample["venues"].values())
    perp_usable = sum(v["market"] == "perpetual" and any(b["imbalance_bid_share"] is not None for b in v["bands"].values()) for v in sample["venues"].values())
    latest = {
        "schema_version": 1, "generated_at": now.isoformat(),
        "status": "ok" if spot_usable >= 2 and perp_usable >= 2 else "partial" if spot_usable + perp_usable else "unavailable",
        "spot_venues": spot_count, "perpetual_venues": perp_count,
        "spot_usable_venues": spot_usable, "perpetual_usable_venues": perp_usable,
        "current": sample if sample["venues"] else None,
        "spot_and_perpetual_are_not_aggregated": True,
        "comparisons": compare_lookback(samples, now),
        "spot_daily": daily_summary(samples),
        "archived_futures": {"range": [ARCHIVE_START.isoformat(), ARCHIVE_LAST_SAFE.isoformat()],
                             "available_days": len(archive), "days_with_errors": sum(bool(x.get("error")) for x in checks.values()),
                             "last_valid_day": max(archive, default=None),
                             "history_file": "btc-liquidity/data/history.json",
                             "known_exporter_defect_from": "2026-09-03",
                             "not_comparable_directly_to_current_spot": True},
        "methodology": "Visible resting limit orders, not executed volume or firm liquidity; public REST snapshot sampled hourly. Quote USDT treated as near USD, not exact FX conversion. Band value null when book reach is insufficient; venue and instrument never silently aggregated. Changes require identical venue and band, observed earlier sample <=3h from target. Historical Binance USD-M bookDepth is pre-known-defect daily median, not a current book.",
        "errors": errors[-30:],
    }
    write(ROOT / "latest.json", latest)
    print(json.dumps({"status": latest["status"], "venues": list(sample["venues"]), "futures_archive_days": len(archive), "errors": errors[:8]}))

if __name__ == "__main__":
    main()
